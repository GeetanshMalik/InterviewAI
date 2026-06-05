from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, status

from config import settings
from services.execution_engine import run_code_suite


LANGUAGE_ALIASES = {
    "python": ["python (3", "python 3", "python3"],
    "javascript": ["javascript", "node.js", "nodejs"],
    "typescript": ["typescript"],
    "java": ["java", "openjdk"],
    "cpp": ["c++"],
    "c": ["c ("],
    "csharp": ["c#", "csharp"],
    "go": ["go (", "golang"],
    "rust": ["rust"],
    "ruby": ["ruby"],
    "php": ["php"],
    "kotlin": ["kotlin"],
    "swift": ["swift"],
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

LANGUAGE_NORMALIZATION = {
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "c++": "cpp",
    "cplusplus": "cpp",
    "cs": "csharp",
    "c#": "csharp",
    "golang": "go",
}

LOCAL_RUNNER_LANGUAGES = {
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


def _normalize_language(language: str) -> str:
    cleaned = str(language or "javascript").strip().lower()
    return LANGUAGE_NORMALIZATION.get(cleaned, cleaned)


def _which(command: str) -> str | None:
    return shutil.which(command)


def _missing_runtime(language: str, requirements: str) -> HTTPException:
    label = LANGUAGE_LABELS.get(language, language)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            f"{label} execution needs {requirements} installed locally, or a reachable Judge0 runtime at "
            f"{settings.judge0_base_url}. Try another language or start Judge0, then retry."
        ),
    )


def _executable_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


def _repo_bin(command: str) -> str | None:
    suffix = ".cmd" if os.name == "nt" else ""
    candidate = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / f"{command}{suffix}"
    return str(candidate) if candidate.exists() else None


def _local_runner_commands(language: str, source_path: Path, temp_dir: Path) -> tuple[list[str] | None, list[str]]:
    executable_path = temp_dir / _executable_name("submission")

    if language == "python":
        return None, [sys.executable, str(source_path)]

    if language == "javascript":
        node = _which("node")
        if not node:
            raise _missing_runtime(language, "Node.js")
        return None, [node, str(source_path)]

    if language == "typescript":
        node = _which("node")
        if not node:
            raise _missing_runtime(language, "Node.js")
        tsx = _which("tsx")
        if tsx:
            return None, [tsx, str(source_path)]
        ts_node = _which("ts-node")
        if ts_node:
            return None, [ts_node, "--compiler-options", '{"module":"CommonJS"}', str(source_path)]
        tsc = _which("tsc") or _repo_bin("tsc")
        if tsc:
            output_path = temp_dir / "submission.js"
            return [
                tsc,
                str(source_path),
                "--target",
                "ES2020",
                "--module",
                "commonjs",
                "--outDir",
                str(temp_dir),
                "--skipLibCheck",
            ], [node, str(output_path)]
        raise _missing_runtime(language, "tsx, ts-node, or the TypeScript compiler")

    if language == "c":
        gcc = _which("gcc")
        if not gcc:
            raise _missing_runtime(language, "GCC")
        return [gcc, str(source_path), "-O2", "-std=c11", "-o", str(executable_path)], [str(executable_path)]

    if language == "cpp":
        compiler = _which("g++") or _which("clang++")
        if not compiler:
            raise _missing_runtime(language, "g++ or clang++")
        return [compiler, str(source_path), "-O2", "-std=c++17", "-o", str(executable_path)], [str(executable_path)]

    if language == "java":
        javac = _which("javac")
        java = _which("java")
        if not javac or not java:
            raise _missing_runtime(language, "JDK javac and java")
        return [javac, "-parameters", str(source_path)], [java, "-cp", str(temp_dir), "Main"]

    if language == "csharp":
        compiler = _which("csc") or _which("mcs")
        if not compiler:
            raise _missing_runtime(language, "csc or mcs")
        return [compiler, f"-out:{executable_path}", str(source_path)], [str(executable_path)]

    if language == "go":
        go = _which("go")
        if not go:
            raise _missing_runtime(language, "Go")
        return [go, "build", "-o", str(executable_path), str(source_path)], [str(executable_path)]

    if language == "rust":
        rustc = _which("rustc")
        if not rustc:
            raise _missing_runtime(language, "rustc")
        return [rustc, str(source_path), "-O", "-o", str(executable_path)], [str(executable_path)]

    if language == "ruby":
        ruby = _which("ruby")
        if not ruby:
            raise _missing_runtime(language, "Ruby")
        return None, [ruby, str(source_path)]

    if language == "php":
        php = _which("php")
        if not php:
            raise _missing_runtime(language, "PHP")
        return None, [php, str(source_path)]

    if language == "kotlin":
        kotlinc = _which("kotlinc")
        java = _which("java")
        if not kotlinc or not java:
            raise _missing_runtime(language, "Kotlin compiler and Java")
        jar_path = temp_dir / "submission.jar"
        return [kotlinc, str(source_path), "-include-runtime", "-d", str(jar_path)], [java, "-jar", str(jar_path)]

    if language == "swift":
        swift = _which("swift")
        if not swift:
            raise _missing_runtime(language, "Swift")
        return None, [swift, str(source_path)]

    raise _missing_runtime(language, "a supported compiler or runtime")


def _local_source_name(language: str) -> str:
    names = {
        "python": "submission.py",
        "javascript": "submission.js",
        "typescript": "submission.ts",
        "java": "Main.java",
        "cpp": "submission.cpp",
        "c": "submission.c",
        "csharp": "submission.cs",
        "go": "submission.go",
        "rust": "submission.rs",
        "ruby": "submission.rb",
        "php": "submission.php",
        "kotlin": "submission.kt",
        "swift": "submission.swift",
    }
    return names.get(language, "submission.txt")


def _json_compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _candidate_function_names(problem_title: str | None = None) -> list[str]:
    names = ["solution", "main"]
    if problem_title:
        words = re.findall(r"[A-Za-z0-9]+", problem_title)
        if words:
            snake = "_".join(word.lower() for word in words)
            camel = words[0].lower() + "".join(word[:1].upper() + word[1:] for word in words[1:])
            names.extend([snake, camel])
    return list(dict.fromkeys(names))


def _inject_into_java_main(code: str, helper: str) -> str:
    if not re.search(r"\bclass\s+Main\b", code):
        return code
    insert_at = code.rfind("}")
    if insert_at == -1:
        return code
    return f"{code[:insert_at].rstrip()}\n\n{helper}\n{code[insert_at:]}"


def _wrap_go_source(code: str) -> str:
    if re.search(r"\bfunc\s+main\s*\(", code):
        return code
    source = code if re.search(r"(?m)^\s*package\s+main\s*$", code) else f"package main\n\n{code}"
    source = re.sub(
        r"(?m)^(\s*package\s+main\s*)$",
        r"""\1

import (
    "__INTERVIEWOS_ENCODING_JSON__"
    "__INTERVIEWOS_IO__"
    "__INTERVIEWOS_OS__"
    "__INTERVIEWOS_REFLECT__"
    "__INTERVIEWOS_STRINGS__"
)""",
        source,
        count=1,
    )
    source = source.replace('"__INTERVIEWOS_ENCODING_JSON__"', '"encoding/json"')
    source = source.replace('"__INTERVIEWOS_IO__"', '"io"')
    source = source.replace('"__INTERVIEWOS_OS__"', '"os"')
    source = source.replace('"__INTERVIEWOS_REFLECT__"', '"reflect"')
    source = source.replace('"__INTERVIEWOS_STRINGS__"', '"strings"')
    return f"""{source.rstrip()}

func main() {{
    rawInput, err := io.ReadAll(os.Stdin)
    if err != nil {{
        panic(err)
    }}
    var parsedInput interface{{}}
    if strings.TrimSpace(string(rawInput)) != "" {{
        if err := json.Unmarshal(rawInput, &parsedInput); err != nil {{
            panic(err)
        }}
    }}
    result := __interviewosCallSolve(parsedInput)
    output, err := json.Marshal(result)
    if err != nil {{
        panic(err)
    }}
    _, _ = os.Stdout.Write(output)
}}

func __interviewosCallSolve(input interface{{}}) interface{{}} {{
    fn := reflect.ValueOf(solve)
    fnType := fn.Type()
    if fnType.NumIn() == 0 {{
        results := fn.Call(nil)
        if len(results) == 0 {{
            return nil
        }}
        return results[0].Interface()
    }}

    target := fnType.In(0)
    arg := input
    value := reflect.ValueOf(arg)
    if !value.IsValid() {{
        value = reflect.Zero(target)
    }} else if value.Type().AssignableTo(target) {{
        // Already correct.
    }} else if value.Type().ConvertibleTo(target) {{
        value = value.Convert(target)
    }} else {{
        value = reflect.Zero(target)
    }}

    args := []reflect.Value{{value}}
    for index := 1; index < fnType.NumIn(); index++ {{
        args = append(args, reflect.Zero(fnType.In(index)))
    }}

    results := fn.Call(args)
    if len(results) == 0 {{
        return nil
    }}
    return results[0].Interface()
}}
"""


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.judge0_api_key:
        headers[settings.judge0_auth_header] = settings.judge0_api_key
    if settings.judge0_rapidapi_host:
        headers["X-RapidAPI-Host"] = settings.judge0_rapidapi_host
    return headers


async def _language_id(client: httpx.AsyncClient, language: str) -> int:
    language = _normalize_language(language)
    wanted = LANGUAGE_ALIASES.get(language)
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{language} is not configured for Judge0 execution.",
        )

    response = await client.get("/languages", headers=_headers())
    response.raise_for_status()
    languages = response.json()
    for candidate in languages:
        name = str(candidate.get("name", "")).lower()
        if any(alias in name for alias in wanted):
            return int(candidate["id"])

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Judge0 is running but does not expose a {language} runtime.",
    )


def _wrap_source(code: str, language: str, adapter_names: list[str]) -> str:
    language = _normalize_language(language)
    if language == "python":
        names_literal = repr(adapter_names)
        return f"""{code}

if __name__ == "__main__":
    import inspect
    import json
    import sys

    def __interviewos_adapt_call(fn, parsed_input):
        signature = inspect.signature(fn)
        params = list(signature.parameters)
        if isinstance(parsed_input, dict):
            if len(params) == 1:
                key = params[0]
                if key in parsed_input:
                    return fn(parsed_input[key])
                if len(parsed_input) == 1:
                    return fn(next(iter(parsed_input.values())))
                return fn(parsed_input)
            if params and all(param in parsed_input for param in params):
                return fn(**{{param: parsed_input[param] for param in params}})
        return fn(parsed_input)

    if "solve" not in globals():
        for __interviewos_name in {names_literal}:
            __interviewos_candidate = globals().get(__interviewos_name)
            if inspect.isfunction(__interviewos_candidate):
                def solve(parsed_input, __interviewos_fn=__interviewos_candidate):
                    return __interviewos_adapt_call(__interviewos_fn, parsed_input)
                break

    if "solve" not in globals():
        __interviewos_functions = [
            candidate
            for name, candidate in globals().items()
            if inspect.isfunction(candidate)
            and getattr(candidate, "__module__", "") == "__main__"
            and not name.startswith("__interviewos")
        ]
        if len(__interviewos_functions) == 1:
            def solve(parsed_input, __interviewos_fn=__interviewos_functions[0]):
                return __interviewos_adapt_call(__interviewos_fn, parsed_input)

    raw_input = sys.stdin.read().strip()
    parsed_input = json.loads(raw_input) if raw_input else None
    result = solve(parsed_input)
    print(json.dumps(result, separators=(",", ":")))
"""
    if language in {"javascript", "typescript"}:
        names_literal = json.dumps(adapter_names)
        prefix = 'declare const require: any;\ndeclare const process: any;\n' if language == "typescript" else ""
        return f"""{prefix}{code}

const fs = require("fs");
const __interviewosAdapterNames = {names_literal};
function __interviewosParams(fn) {{
  const source = Function.prototype.toString.call(fn);
  const match = source.match(/^[^(]*\\(([^)]*)\\)/);
  if (!match) return [];
  return match[1].split(",").map((part) => part.trim()).filter(Boolean);
}}
function __interviewosAdaptCall(fn, input) {{
  const params = __interviewosParams(fn);
  if (input && typeof input === "object" && !Array.isArray(input)) {{
    const keys = Object.keys(input);
    if (params.length === 1) {{
      if (Object.prototype.hasOwnProperty.call(input, params[0])) return fn(input[params[0]]);
      if (keys.length === 1) return fn(input[keys[0]]);
      return fn(input);
    }}
    if (params.length > 1 && params.every((param) => Object.prototype.hasOwnProperty.call(input, param))) {{
      return fn(...params.map((param) => input[param]));
    }}
  }}
  return fn(input);
}}
let __interviewosSolve = typeof solve === "function" ? solve : null;
if (!__interviewosSolve) {{
  for (const name of __interviewosAdapterNames) {{
    try {{
      const candidate = eval(name);
      if (typeof candidate === "function") {{
        __interviewosSolve = (input) => __interviewosAdaptCall(candidate, input);
        break;
      }}
    }} catch {{
      // Candidate name is not defined in the submitted code.
    }}
  }}
}}
const rawInput = fs.readFileSync(0, "utf8").trim();
const parsedInput = rawInput ? JSON.parse(rawInput) : null;
Promise.resolve(__interviewosSolve(parsedInput))
  .then((result) => process.stdout.write(JSON.stringify(result)))
    .catch((error) => {{
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }});
"""
    if language == "java":
        if re.search(r"\bstatic\s+void\s+main\s*\(", code):
            return code
        helper = r"""
    public static void main(String[] args) throws Exception {
        String rawInput = __interviewosReadStdin().trim();
        Object parsedInput = rawInput.isEmpty() ? null : __InterviewOSJson.parse(rawInput);
        Object result = __interviewosCallSolve(parsedInput);
        System.out.print(__InterviewOSJson.stringify(result));
    }

    private static String __interviewosReadStdin() throws Exception {
        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int read;
        while ((read = System.in.read(chunk)) != -1) {
            buffer.write(chunk, 0, read);
        }
        return buffer.toString(java.nio.charset.StandardCharsets.UTF_8.name());
    }

    private static Object __interviewosCallSolve(Object input) throws Exception {
        java.lang.reflect.Method[] methods = Main.class.getDeclaredMethods();
        for (java.lang.reflect.Method method : methods) {
            if (!method.getName().equals("solve")) {
                continue;
            }
            method.setAccessible(true);
            Object target = java.lang.reflect.Modifier.isStatic(method.getModifiers())
                ? null
                : Main.class.getDeclaredConstructor().newInstance();
            return method.invoke(target, __interviewosBuildArgs(method, input));
        }
        throw new IllegalStateException("Define a solve(input) method in class Main.");
    }

    private static Object[] __interviewosBuildArgs(java.lang.reflect.Method method, Object input) {
        java.lang.reflect.Parameter[] parameters = method.getParameters();
        if (parameters.length == 0) {
            return new Object[0];
        }
        if (parameters.length == 1) {
            Class<?> targetType = parameters[0].getType();
            if (input instanceof java.util.Map<?, ?>
                && !(targetType == java.util.Map.class || targetType == Object.class || java.util.Map.class.isAssignableFrom(targetType))) {
                java.util.Map<?, ?> map = (java.util.Map<?, ?>) input;
                String name = parameters[0].getName();
                if (map.containsKey(name)) {
                    return new Object[] { __interviewosConvert(map.get(name), targetType) };
                }
                if (map.size() == 1) {
                    return new Object[] { __interviewosConvert(map.values().iterator().next(), targetType) };
                }
            }
            return new Object[] { __interviewosConvert(input, targetType) };
        }
        Object[] args = new Object[parameters.length];
        if (input instanceof java.util.Map<?, ?>) {
            java.util.Map<?, ?> map = (java.util.Map<?, ?>) input;
            int index = 0;
            for (java.lang.reflect.Parameter parameter : parameters) {
                Object value = map.containsKey(parameter.getName()) ? map.get(parameter.getName()) : null;
                args[index++] = __interviewosConvert(value, parameter.getType());
            }
            return args;
        }
        args[0] = __interviewosConvert(input, parameters[0].getType());
        for (int index = 1; index < args.length; index++) {
            args[index] = __interviewosConvert(null, parameters[index].getType());
        }
        return args;
    }

    private static Object __interviewosConvert(Object value, Class<?> targetType) {
        if (value == null) {
            if (targetType == boolean.class) return false;
            if (targetType == byte.class || targetType == short.class || targetType == int.class || targetType == long.class) return 0;
            if (targetType == float.class || targetType == double.class) return 0.0;
            if (targetType == char.class) return '\0';
            return null;
        }
        if (targetType == Object.class || targetType.isInstance(value)) {
            return value;
        }
        if (targetType == String.class) {
            return String.valueOf(value);
        }
        if (value instanceof Number) {
            Number number = (Number) value;
            if (targetType == int.class || targetType == Integer.class) return number.intValue();
            if (targetType == long.class || targetType == Long.class) return number.longValue();
            if (targetType == double.class || targetType == Double.class) return number.doubleValue();
            if (targetType == float.class || targetType == Float.class) return number.floatValue();
            if (targetType == short.class || targetType == Short.class) return number.shortValue();
            if (targetType == byte.class || targetType == Byte.class) return number.byteValue();
        }
        if ((targetType == boolean.class || targetType == Boolean.class) && value instanceof Boolean) {
            return value;
        }
        return value;
    }

    private static final class __InterviewOSJson {
        private final String source;
        private int index;

        private __InterviewOSJson(String source) {
            this.source = source;
        }

        static Object parse(String source) {
            return new __InterviewOSJson(source).parseValue();
        }

        static String stringify(Object value) {
            if (value == null) return "null";
            if (value instanceof String || value instanceof Character) return quote(String.valueOf(value));
            if (value instanceof Number || value instanceof Boolean) return String.valueOf(value);
            if (value instanceof java.util.Map<?, ?>) {
                StringBuilder out = new StringBuilder("{");
                boolean first = true;
                for (java.util.Map.Entry<?, ?> entry : ((java.util.Map<?, ?>) value).entrySet()) {
                    if (!first) out.append(",");
                    first = false;
                    out.append(quote(String.valueOf(entry.getKey()))).append(":").append(stringify(entry.getValue()));
                }
                return out.append("}").toString();
            }
            if (value instanceof Iterable<?>) {
                StringBuilder out = new StringBuilder("[");
                boolean first = true;
                for (Object item : (Iterable<?>) value) {
                    if (!first) out.append(",");
                    first = false;
                    out.append(stringify(item));
                }
                return out.append("]").toString();
            }
            Class<?> type = value.getClass();
            if (type.isArray()) {
                StringBuilder out = new StringBuilder("[");
                int length = java.lang.reflect.Array.getLength(value);
                for (int i = 0; i < length; i++) {
                    if (i > 0) out.append(",");
                    out.append(stringify(java.lang.reflect.Array.get(value, i)));
                }
                return out.append("]").toString();
            }
            return quote(String.valueOf(value));
        }

        private static String quote(String value) {
            StringBuilder out = new StringBuilder("\"");
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
                switch (c) {
                    case '"': out.append("\\\""); break;
                    case '\\': out.append("\\\\"); break;
                    case '\b': out.append("\\b"); break;
                    case '\f': out.append("\\f"); break;
                    case '\n': out.append("\\n"); break;
                    case '\r': out.append("\\r"); break;
                    case '\t': out.append("\\t"); break;
                    default:
                        if (c < 32) {
                            out.append(String.format("\\u%04x", (int) c));
                        } else {
                            out.append(c);
                        }
                }
            }
            return out.append("\"").toString();
        }

        private Object parseValue() {
            skipWhitespace();
            if (index >= source.length()) return null;
            char c = source.charAt(index);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't') {
                index += 4;
                return Boolean.TRUE;
            }
            if (c == 'f') {
                index += 5;
                return Boolean.FALSE;
            }
            if (c == 'n') {
                index += 4;
                return null;
            }
            return parseNumber();
        }

        private java.util.Map<String, Object> parseObject() {
            java.util.Map<String, Object> map = new java.util.LinkedHashMap<>();
            index++;
            skipWhitespace();
            if (peek('}')) {
                index++;
                return map;
            }
            while (index < source.length()) {
                String key = parseString();
                skipWhitespace();
                index++;
                Object value = parseValue();
                map.put(key, value);
                skipWhitespace();
                if (peek('}')) {
                    index++;
                    break;
                }
                index++;
            }
            return map;
        }

        private java.util.List<Object> parseArray() {
            java.util.List<Object> list = new java.util.ArrayList<>();
            index++;
            skipWhitespace();
            if (peek(']')) {
                index++;
                return list;
            }
            while (index < source.length()) {
                list.add(parseValue());
                skipWhitespace();
                if (peek(']')) {
                    index++;
                    break;
                }
                index++;
            }
            return list;
        }

        private String parseString() {
            StringBuilder out = new StringBuilder();
            index++;
            while (index < source.length()) {
                char c = source.charAt(index++);
                if (c == '"') break;
                if (c == '\\' && index < source.length()) {
                    char escaped = source.charAt(index++);
                    switch (escaped) {
                        case '"': out.append('"'); break;
                        case '\\': out.append('\\'); break;
                        case '/': out.append('/'); break;
                        case 'b': out.append('\b'); break;
                        case 'f': out.append('\f'); break;
                        case 'n': out.append('\n'); break;
                        case 'r': out.append('\r'); break;
                        case 't': out.append('\t'); break;
                        case 'u':
                            String hex = source.substring(index, index + 4);
                            out.append((char) Integer.parseInt(hex, 16));
                            index += 4;
                            break;
                        default: out.append(escaped);
                    }
                } else {
                    out.append(c);
                }
            }
            return out.toString();
        }

        private Number parseNumber() {
            int start = index;
            while (index < source.length() && "-+0123456789.eE".indexOf(source.charAt(index)) >= 0) {
                index++;
            }
            String value = source.substring(start, index);
            if (value.contains(".") || value.contains("e") || value.contains("E")) {
                return Double.parseDouble(value);
            }
            long parsed = Long.parseLong(value);
            if (parsed >= Integer.MIN_VALUE && parsed <= Integer.MAX_VALUE) {
                return (int) parsed;
            }
            return parsed;
        }

        private void skipWhitespace() {
            while (index < source.length() && Character.isWhitespace(source.charAt(index))) {
                index++;
            }
        }

        private boolean peek(char expected) {
            return index < source.length() && source.charAt(index) == expected;
        }
    }
"""
        return _inject_into_java_main(code, helper)
    if language == "go":
        return _wrap_go_source(code)
    return code


async def evaluate_with_judge0(code: str, language: str, test_cases: list[dict], problem_title: str | None = None) -> dict:
    language = _normalize_language(language)
    if not test_cases:
        raise HTTPException(status_code=400, detail="This generated problem has no test cases.")

    if str(settings.code_execution_backend or "internal").strip().lower() != "judge0":
        return await _evaluate_with_internal_execution_engine(code, language, test_cases, problem_title)

    if settings.enable_local_code_runner and settings.prefer_local_code_runner:
        try:
            return _evaluate_with_local_runner(
                code,
                language,
                test_cases,
                problem_title,
                "Local development runner selected before Judge0 for faster feedback.",
            )
        except HTTPException as exc:
            if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
                raise

    try:
        async with httpx.AsyncClient(
            base_url=settings.judge0_base_url.rstrip("/"),
            timeout=settings.judge0_timeout_seconds,
        ) as client:
            language_id = await _language_id(client, language)
            source = _wrap_source(code, language, _candidate_function_names(problem_title))
            results = []
            for index, case in enumerate(test_cases, start=1):
                payload = {
                    "language_id": language_id,
                    "source_code": source,
                    "stdin": _json_compact(case.get("input")),
                }
                response = await client.post(
                    "/submissions",
                    params={"base64_encoded": "false", "wait": "true"},
                    headers=_headers(),
                    json=payload,
                )
                response.raise_for_status()
                run = response.json()
                status_data = run.get("status", {})
                status_id = int(status_data.get("id", 0))
                if status_id == 13 and settings.enable_local_code_runner:
                    return _evaluate_with_local_runner(
                        code,
                        language,
                        test_cases,
                        problem_title,
                        f"Judge0 internal error: {run.get('message') or status_data.get('description')}",
                    )
                actual = _parse_actual(run.get("stdout"))
                expected = _normalize_expected(case.get("expected"))
                accepted = status_id == 3 and _values_equal(actual, expected)
                results.append(
                    {
                        "name": case.get("name", f"Case {index}"),
                        "input": case.get("input"),
                        "expected": expected,
                        "actual": actual,
                        "stdout": run.get("stdout"),
                        "stderr": run.get("stderr"),
                        "compileOutput": run.get("compile_output"),
                        "message": run.get("message"),
                        "time": run.get("time"),
                        "memory": run.get("memory"),
                        "status": status_data.get("description", "Unknown"),
                        "passed": accepted,
                    }
                )
    except HTTPException:
        raise
    except httpx.RequestError:
        if settings.enable_local_code_runner:
            return _evaluate_with_local_runner(
                code,
                language,
                test_cases,
                problem_title,
                f"Judge0 is not reachable at {settings.judge0_base_url}.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Judge0 is not reachable at {settings.judge0_base_url}. "
                "Start free self-hosted Judge0 CE locally, then retry."
            ),
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Judge0 returned HTTP {exc.response.status_code}: {exc.response.text}",
        )

    passed = sum(1 for result in results if result["passed"])
    score = round((passed / len(results)) * 100, 2)
    return {
        "status": "passed" if passed == len(results) else "failed",
        "score": score,
        "language": language,
        "test_results": results,
        "feedback": (
            "All generated Judge0 test cases passed."
            if passed == len(results)
            else f"{passed}/{len(results)} generated Judge0 test cases passed."
        ),
    }


async def _evaluate_with_internal_execution_engine(
    code: str,
    language: str,
    test_cases: list[dict],
    problem_title: str | None,
) -> dict:
    source = _wrap_source(code, language, _candidate_function_names(problem_title))
    suite = await run_code_suite(
        source,
        language,
        [_json_compact(case.get("input")) for case in test_cases],
    )
    results = []
    for index, case in enumerate(test_cases, start=1):
        run = suite.results[index - 1]
        actual = _parse_actual(run.stdout)
        expected = _normalize_expected(case.get("expected"))
        accepted = run.status == "Accepted" and _values_equal(actual, expected)
        results.append(
            {
                "name": case.get("name", f"Case {index}"),
                "input": case.get("input"),
                "expected": expected,
                "actual": actual,
                "stdout": run.stdout,
                "stderr": run.stderr,
                "compileOutput": run.compile_output or suite.compile_output,
                "compile_output": run.compile_output or suite.compile_output,
                "message": None,
                "time": run.execution_time,
                "execution_time": run.execution_time,
                "memory": run.memory_usage,
                "memory_usage": run.memory_usage,
                "exitCode": run.exit_code,
                "exit_code": run.exit_code,
                "status": run.status,
                "timedOut": run.timed_out,
                "outputTruncated": run.output_truncated,
                "passed": accepted,
            }
        )

    passed = sum(1 for result in results if result["passed"])
    score = round((passed / len(results)) * 100, 2)
    return {
        "status": "passed" if passed == len(results) else "failed",
        "score": score,
        "language": language,
        "engine": suite.engine,
        "compile_output": suite.compile_output,
        "compile_exit_code": suite.compile_exit_code,
        "compile_time": suite.compile_time,
        "compile_timed_out": suite.compile_timed_out,
        "test_results": results,
        "feedback": (
            "All generated internal execution test cases passed."
            if passed == len(results)
            else f"{passed}/{len(results)} generated internal execution test cases passed."
        ),
    }


def _evaluate_with_local_runner(
    code: str,
    language: str,
    test_cases: list[dict],
    problem_title: str | None,
    reason: str,
) -> dict:
    language = _normalize_language(language)
    if language not in LOCAL_RUNNER_LANGUAGES:
        label = LANGUAGE_LABELS.get(language, language)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{label} execution requires a reachable Judge0 runtime at {settings.judge0_base_url}. "
                "Local fallback is not configured for this language."
            ),
        )
    source = _wrap_source(code, language, _candidate_function_names(problem_title))

    results = []
    with tempfile.TemporaryDirectory(prefix="interviewos-run-") as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / _local_source_name(language)
        source_path.write_text(source, encoding="utf-8")
        compile_command, run_command = _local_runner_commands(language, source_path, temp_path)

        compile_output = None
        if compile_command:
            try:
                compiled = subprocess.run(
                    compile_command,
                    text=True,
                    capture_output=True,
                    timeout=settings.local_code_runner_compile_timeout_seconds,
                    cwd=temp_dir,
                )
            except subprocess.TimeoutExpired as exc:
                compile_output = exc.stderr or exc.stdout or "Compilation timed out."
                compiled = None
            except OSError as exc:
                compile_output = str(exc)
                compiled = None

            if compiled is None or compiled.returncode != 0:
                compile_output = compile_output or (compiled.stderr or compiled.stdout or "Compilation failed.")
                for index, case in enumerate(test_cases, start=1):
                    results.append(
                        {
                            "name": case.get("name", f"Case {index}"),
                            "input": case.get("input"),
                            "expected": _normalize_expected(case.get("expected")),
                            "actual": None,
                            "stdout": None,
                            "stderr": None,
                            "compileOutput": compile_output,
                            "message": reason,
                            "time": None,
                            "memory": None,
                            "status": "Compilation Error",
                            "passed": False,
                        }
                    )
                return _local_evaluation_response(language, results, "Compilation failed while using the local development runner.")

        for index, case in enumerate(test_cases, start=1):
            expected = _normalize_expected(case.get("expected"))
            completed: subprocess.CompletedProcess[str] | None = None
            try:
                completed = subprocess.run(
                    run_command,
                    input=_json_compact(case.get("input")),
                    text=True,
                    capture_output=True,
                    timeout=settings.local_code_runner_timeout_seconds,
                    cwd=temp_dir,
                )
                actual = _parse_actual(completed.stdout)
                accepted = completed.returncode == 0 and _values_equal(actual, expected)
                status_text = "Accepted" if completed.returncode == 0 else "Runtime Error"
                stderr = completed.stderr or None
            except subprocess.TimeoutExpired as exc:
                actual = None
                accepted = False
                status_text = "Time Limit Exceeded"
                stderr = (exc.stderr or "Local execution timed out.")
            except OSError as exc:
                actual = None
                accepted = False
                status_text = "Execution Error"
                stderr = str(exc)

            results.append(
                {
                    "name": case.get("name", f"Case {index}"),
                    "input": case.get("input"),
                    "expected": expected,
                    "actual": actual,
                    "stdout": completed.stdout if completed else None,
                    "stderr": stderr,
                    "compileOutput": None,
                    "message": reason,
                    "time": None,
                    "memory": None,
                    "status": status_text,
                    "passed": accepted,
                }
            )

    passed = sum(1 for result in results if result["passed"])
    feedback = (
        "All test cases passed using the local development runner."
        if passed == len(results)
        else f"{passed}/{len(results)} test cases passed using the local development runner."
    )
    return _local_evaluation_response(language, results, feedback)


def _local_evaluation_response(language: str, results: list[dict], feedback: str) -> dict:
    passed = sum(1 for result in results if result["passed"])
    score = round((passed / len(results)) * 100, 2) if results else 0
    return {
        "status": "passed" if results and passed == len(results) else "failed",
        "score": score,
        "language": language,
        "test_results": results,
        "feedback": feedback,
    }


def _parse_actual(stdout: str | None) -> Any:
    if stdout is None:
        return None
    cleaned = stdout.strip()
    if not cleaned:
        return ""
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned


def _normalize_expected(expected: Any) -> Any:
    if isinstance(expected, str):
        cleaned = expected.strip()
        if cleaned:
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                lowered = cleaned.lower()
                if lowered == "true":
                    return True
                if lowered == "false":
                    return False
                if lowered == "null":
                    return None
    return expected


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) < 1e-9
    return actual == expected
