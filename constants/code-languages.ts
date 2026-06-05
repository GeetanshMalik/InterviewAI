export type CodeLanguage = {
  value: string;
  label: string;
  monaco: string;
  tabSize: number;
  starter: string;
  contract: string;
};

export const codeLanguages: CodeLanguage[] = [
  {
    value: "javascript",
    label: "JavaScript",
    monaco: "javascript",
    tabSize: 2,
    contract: "Implement solve(input) and return a JSON-serializable value.",
    starter: `function solve(input) {
  // input is a JSON object from the test case.
  // Return the expected JSON value.
  return null;
}`,
  },
  {
    value: "typescript",
    label: "TypeScript",
    monaco: "typescript",
    tabSize: 2,
    contract: "Implement solve(input) and return a JSON-serializable value.",
    starter: `function solve(input: any): any {
  // input is parsed JSON from the test case.
  return null;
}`,
  },
  {
    value: "python",
    label: "Python",
    monaco: "python",
    tabSize: 4,
    contract: "Implement solve(input) and return a JSON-serializable value.",
    starter: `def solve(input):
    # input is a dict/list/value from the test case.
    # Return the expected JSON value.
    return None`,
  },
  {
    value: "java",
    label: "Java",
    monaco: "java",
    tabSize: 4,
    contract: "Implement static solve(input) in class Main and return a JSON-serializable value.",
    starter: `import java.util.*;

public class Main {
    public static Object solve(Map<String, Object> input) {
        // input is a JSON object from the test case.
        // Return the expected JSON value.
        return null;
    }
}`,
  },
  {
    value: "cpp",
    label: "C++",
    monaco: "cpp",
    tabSize: 2,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `#include <bits/stdc++.h>
using namespace std;

int main() {
  string input((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());

  // Parse input and print the expected JSON output.
  cout << "null";
  return 0;
}`,
  },
  {
    value: "c",
    label: "C",
    monaco: "c",
    tabSize: 2,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `#include <stdio.h>

int main(void) {
  // Read stdin, parse input, and print the expected JSON output.
  printf("null");
  return 0;
}`,
  },
  {
    value: "csharp",
    label: "C#",
    monaco: "csharp",
    tabSize: 4,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `using System;

public class MainClass {
    public static void Main() {
        string input = Console.In.ReadToEnd();

        // Parse input and print the expected JSON output.
        Console.Write("null");
    }
}`,
  },
  {
    value: "go",
    label: "Go",
    monaco: "go",
    tabSize: 4,
    contract: "Implement solve(input) and return a JSON-serializable value.",
    starter: `package main

func solve(input map[string]interface{}) interface{} {
    // input is a JSON object from the test case.
    // Return the expected JSON value.
    return nil
}`,
  },
  {
    value: "rust",
    label: "Rust",
    monaco: "rust",
    tabSize: 4,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `use std::io::{self, Read};

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();

    // Parse input and print the expected JSON output.
    print!("null");
}`,
  },
  {
    value: "ruby",
    label: "Ruby",
    monaco: "ruby",
    tabSize: 2,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `require "json"

input = STDIN.read.strip
parsed = input.empty? ? nil : JSON.parse(input)

# Use parsed input and print the expected JSON output.
print JSON.generate(nil)`,
  },
  {
    value: "php",
    label: "PHP",
    monaco: "php",
    tabSize: 4,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `<?php
$input = trim(stream_get_contents(STDIN));
$parsed = $input === "" ? null : json_decode($input, true);

// Use $parsed and print the expected JSON output.
echo json_encode(null);
?>`,
  },
  {
    value: "kotlin",
    label: "Kotlin",
    monaco: "kotlin",
    tabSize: 4,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `fun main() {
    val input = generateSequence(::readLine).joinToString("\\n")

    // Parse input and print the expected JSON output.
    print("null")
}`,
  },
  {
    value: "swift",
    label: "Swift",
    monaco: "swift",
    tabSize: 4,
    contract: "Write a complete program that reads JSON from stdin and prints JSON to stdout.",
    starter: `import Foundation

let input = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""

// Parse input and print the expected JSON output.
print("null", terminator: "")`,
  },
];

export const defaultCodeLanguage = "javascript";

export function getCodeLanguage(value?: string) {
  return (
    codeLanguages.find((language) => language.value === value) ||
    codeLanguages.find((language) => language.value === defaultCodeLanguage)!
  );
}
