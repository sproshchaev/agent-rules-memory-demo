"""Короткая сводка сессии агента из потока событий codex exec --json.

Сам поток в репозиторий не кладется: в нем временные пути и служебные данные.
Сохраняются модель (передается аргументом: в событиях ее нет), число выполненных команд,
прочитан ли SKILL.md и время сессии. «Прочитан» значит: в одной из команд агента есть
строка SKILL.md, сама команда сохраняется в skill_command.
"""
import json
import sys


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def main() -> None:
    path, seconds, model = sys.argv[1], sys.argv[2], sys.argv[3]
    commands, skill_read, tokens, skill_cmd = 0, False, {}, ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            completed = event.get("type") == "item.completed"
            for node in walk(event):
                if completed and node.get("type") == "command_execution":
                    commands += 1
                    cmd = str(node.get("command", ""))
                    if "SKILL.md" in cmd:
                        skill_read = True
                        skill_cmd = skill_cmd or cmd.splitlines()[0][:120]
                if isinstance(node.get("usage"), dict):
                    tokens = node["usage"]
    print(f"model: {model}")
    print(f"commands: {commands}")
    print(f"skill_read: {'yes' if skill_read else 'no'}")
    if skill_cmd:
        print(f"skill_command: {skill_cmd}")
    print(f"seconds: {seconds}")
    for key in ("input_tokens", "output_tokens"):
        if key in tokens:
            print(f"{key}: {tokens[key]}")


if __name__ == "__main__":
    main()
