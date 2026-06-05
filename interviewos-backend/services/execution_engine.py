from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from config import settings

try:
    import resource
except ImportError:  # pragma: no cover - Windows/local dev fallback.
    resource = None  # type: ignore[assignment]


SUPPORTED_EXECUTION_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "java",
    "cpp",
    "c",
    "csharp",
    "go",
    "rust",
    "ruby",
    "php",
    "kotlin",
    "swift",
}


LANGUAGE_LABELS = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "cpp": "C++",
    "c": "C",
    "csharp": "C#",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "php": "PHP",
    "kotlin": "Kotlin",
    "swift": "Swift",
}


SOURCE_NAMES = {
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "java": "Main.java",
    "cpp": "main.cpp",
    "c": "main.c",
    "csharp": "Program.cs",
    "go": "main.go",
    "rust": "main.rs",
    "ruby": "main.rb",
    "php": "main.php",
    "kotlin": "Main.kt",
    "swift": "main.swift",
}


@dataclass(frozen=True)
class ProcessResult:
    stdout: str
    stderr: str
    exit_code: int | None
    execution_time: float
    memory_usage: int | None
    timed_out: bool
    output_truncated: bool


@dataclass(frozen=True)
class ExecutionCaseResult:
    stdout: str | None
    stderr: str | None
    compile_output: str | None
    execution_time: float | None
    memory_usage: int | None
    exit_code: int | None
    status: str
    timed_out: bool
    output_truncated: bool


@dataclass(frozen=True)
class ExecutionSuiteResult:
    language: str
    engine: str
    compile_output: str | None
    compile_exit_code: int | None
    compile_time: float | None
    compile_timed_out: bool
    results: list[ExecutionCaseResult]


def _workspace_root() -> Path:
    configured = str(settings.code_execution_workspace_dir or "").strip()
    if configured in {"./data/code_execution", "data/code_execution"}:
        root = Path(tempfile.gettempdir()) / "interviewos-code-execution"
    else:
        root = Path(configured)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _executable_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _require_command(command: str, language: str) -> str:
    resolved = shutil.which(command)
    if resolved:
        return resolved
    label = LANGUAGE_LABELS.get(language, language)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"{label} runtime is not installed in the execution image. Missing command: {command}.",
    )


def _truncate_output(value: str | bytes | None) -> tuple[str, bool]:
    if value is None:
        return "", False
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    limit = max(1, int(settings.code_execution_max_output_bytes))
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= limit:
        return value, False
    truncated = encoded[:limit].decode("utf-8", "ignore")
    return f"{truncated}\n[output truncated]", True


def _resource_usage_kb() -> int | None:
    if resource is None:
        return None
    try:
        return int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    except Exception:
        return None


def _limit_child_process(timeout_seconds: int):
    if resource is None or os.name == "nt":
        return None

    def _apply_limits() -> None:
        cpu_limit = max(1, timeout_seconds + 1)
        memory_limit_mb = int(settings.code_execution_memory_limit_mb)
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
        except Exception:
            pass
        if memory_limit_mb > 0:
            memory_bytes = memory_limit_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            except Exception:
                pass

    return _apply_limits


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except Exception:
        process.kill()


def _runtime_env(work_dir: Path) -> dict[str, str]:
    env = {
        "HOME": str(work_dir),
        "TMPDIR": str(work_dir),
        "TEMP": str(work_dir),
        "TMP": str(work_dir),
        "NO_COLOR": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "NPM_CONFIG_CACHE": str(work_dir / ".npm"),
        "CARGO_HOME": str(work_dir / ".cargo"),
    }
    if os.environ.get("PATH"):
        env["PATH"] = os.environ["PATH"]
    if os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    stdin: str | None,
    timeout_seconds: int,
) -> ProcessResult:
    started = time.perf_counter()
    memory_before = _resource_usage_kb()
    output_truncated = False
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=_runtime_env(cwd),
        stdin=subprocess.PIPE if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
        preexec_fn=_limit_child_process(timeout_seconds),
    )
    try:
        stdout_raw, stderr_raw = process.communicate(stdin, timeout=timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(process)
        stdout_raw, stderr_raw = process.communicate()
        if exc.stdout:
            stdout_raw = f"{exc.stdout}{stdout_raw or ''}"
        if exc.stderr:
            stderr_raw = f"{exc.stderr}{stderr_raw or ''}"
        timed_out = True
    elapsed = round(time.perf_counter() - started, 4)
    stdout, stdout_truncated = _truncate_output(stdout_raw)
    stderr, stderr_truncated = _truncate_output(stderr_raw)
    output_truncated = stdout_truncated or stderr_truncated
    memory_after = _resource_usage_kb()
    memory_usage = None
    if memory_after is not None:
        memory_usage = max(memory_after, memory_before or 0)
    return ProcessResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=process.returncode,
        execution_time=elapsed,
        memory_usage=memory_usage,
        timed_out=timed_out,
        output_truncated=output_truncated,
    )


def _write_csharp_project(work_dir: Path) -> None:
    (work_dir / "CodeRunner.csproj").write_text(
        """<Project Sdk=\"Microsoft.NET.Sdk\">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>disable</Nullable>
  </PropertyGroup>
</Project>
""",
        encoding="utf-8",
    )


def _commands(language: str, work_dir: Path, source_path: Path) -> tuple[list[str] | None, list[str]]:
    binary = work_dir / _executable_name("main")
    if language == "python":
        return None, [sys.executable, str(source_path)]
    if language == "javascript":
        return None, [_require_command("node", language), str(source_path)]
    if language == "typescript":
        tsc = _require_command("tsc", language)
        node = _require_command("node", language)
        compiled_dir = work_dir / "dist"
        return [
            tsc,
            str(source_path),
            "--target",
            "ES2020",
            "--module",
            "commonjs",
            "--outDir",
            str(compiled_dir),
            "--skipLibCheck",
        ], [node, str(compiled_dir / "main.js")]
    if language == "java":
        return [_require_command("javac", language), "-parameters", str(source_path)], [
            _require_command("java", language),
            "-cp",
            str(work_dir),
            "Main",
        ]
    if language == "c":
        return [_require_command("gcc", language), str(source_path), "-O2", "-std=c11", "-o", str(binary)], [str(binary)]
    if language == "cpp":
        return [
            _require_command("g++", language),
            str(source_path),
            "-O2",
            "-std=c++17",
            "-o",
            str(binary),
        ], [str(binary)]
    if language == "go":
        return None, [_require_command("go", language), "run", str(source_path)]
    if language == "rust":
        return [_require_command("rustc", language), str(source_path), "-O", "-o", str(binary)], [str(binary)]
    if language == "ruby":
        return None, [_require_command("ruby", language), str(source_path)]
    if language == "php":
        return None, [_require_command("php", language), str(source_path)]
    if language == "kotlin":
        jar_path = work_dir / "main.jar"
        return [
            _require_command("kotlinc", language),
            str(source_path),
            "-include-runtime",
            "-d",
            str(jar_path),
        ], [_require_command("java", language), "-jar", str(jar_path)]
    if language == "csharp":
        _write_csharp_project(work_dir)
        return [
            _require_command("dotnet", language),
            "build",
            "CodeRunner.csproj",
            "-c",
            "Release",
            "-o",
            "out",
            "--nologo",
        ], [_require_command("dotnet", language), "out/CodeRunner.dll"]
    if language == "swift":
        return None, [_require_command("swift", language), str(source_path)]
    raise HTTPException(status_code=400, detail=f"Unsupported execution language: {language}.")


def _compile_failure_cases(
    stdins: list[str],
    *,
    compile_result: ProcessResult,
    status_text: str,
) -> list[ExecutionCaseResult]:
    compile_output = "\n".join(part for part in [compile_result.stdout, compile_result.stderr] if part).strip() or None
    return [
        ExecutionCaseResult(
            stdout=None,
            stderr=None,
            compile_output=compile_output,
            execution_time=None,
            memory_usage=compile_result.memory_usage,
            exit_code=compile_result.exit_code,
            status=status_text,
            timed_out=compile_result.timed_out,
            output_truncated=compile_result.output_truncated,
        )
        for _ in stdins
    ]


def _run_suite_sync(source_code: str, language: str, stdins: list[str]) -> ExecutionSuiteResult:
    language = language.strip().lower()
    if language not in SUPPORTED_EXECUTION_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported execution language: {language}.")

    source_size = len(source_code.encode("utf-8", "replace"))
    if source_size > int(settings.code_execution_max_source_bytes):
        raise HTTPException(status_code=413, detail="Submitted code exceeds the configured source size limit.")

    with tempfile.TemporaryDirectory(prefix="interviewos-exec-", dir=str(_workspace_root())) as raw_dir:
        work_dir = Path(raw_dir)
        source_path = work_dir / SOURCE_NAMES[language]
        source_path.write_text(source_code, encoding="utf-8")
        compile_command, run_command = _commands(language, work_dir, source_path)

        compile_result: ProcessResult | None = None
        if compile_command:
            compile_result = _run_process(
                compile_command,
                cwd=work_dir,
                stdin=None,
                timeout_seconds=int(settings.code_execution_compile_timeout_seconds),
            )
            if compile_result.timed_out or compile_result.exit_code != 0:
                status_text = "Compilation Timeout" if compile_result.timed_out else "Compilation Error"
                return ExecutionSuiteResult(
                    language=language,
                    engine="internal-docker-runtime",
                    compile_output="\n".join(
                        part for part in [compile_result.stdout, compile_result.stderr] if part
                    ).strip()
                    or None,
                    compile_exit_code=compile_result.exit_code,
                    compile_time=compile_result.execution_time,
                    compile_timed_out=compile_result.timed_out,
                    results=_compile_failure_cases(stdins, compile_result=compile_result, status_text=status_text),
                )

        case_results: list[ExecutionCaseResult] = []
        for stdin in stdins:
            run_result = _run_process(
                run_command,
                cwd=work_dir,
                stdin=stdin,
                timeout_seconds=int(settings.code_execution_run_timeout_seconds),
            )
            if run_result.timed_out:
                status_text = "Time Limit Exceeded"
            elif run_result.exit_code == 0:
                status_text = "Accepted"
            else:
                status_text = "Runtime Error"
            case_results.append(
                ExecutionCaseResult(
                    stdout=run_result.stdout,
                    stderr=run_result.stderr,
                    compile_output=None,
                    execution_time=run_result.execution_time,
                    memory_usage=run_result.memory_usage,
                    exit_code=run_result.exit_code,
                    status=status_text,
                    timed_out=run_result.timed_out,
                    output_truncated=run_result.output_truncated,
                )
            )

        return ExecutionSuiteResult(
            language=language,
            engine="internal-docker-runtime",
            compile_output=None,
            compile_exit_code=compile_result.exit_code if compile_result else None,
            compile_time=compile_result.execution_time if compile_result else None,
            compile_timed_out=bool(compile_result.timed_out) if compile_result else False,
            results=case_results,
        )


async def run_code_suite(source_code: str, language: str, stdins: list[str]) -> ExecutionSuiteResult:
    return await asyncio.to_thread(_run_suite_sync, source_code, language, stdins)
