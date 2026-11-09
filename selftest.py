"""Позитивный и негативный контроль check.py, для каждого круга.

1. Исходный проект и эталонное решение (reference/) нарушений не дают.
2. Эталон проходит свои тесты и приемочный тест.
3. Каждое подложенное нарушение ловится, и ловится только своей проверкой.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check import DYNAMIC, ROOT, ROUNDS, acceptance, broken_keys, check

# Подложенное нарушение: (файл, что заменить, на что). None вместо «что» значит дописать в конец.
MUTATIONS = {
    "money_int": ("app/subscriptions.py", None, "\n\ndef _x(p):\n    return float(p)\n"),
    "money_name": ("migrations/009_extra.sql", None,
                   "CREATE TABLE extra (\n    id TEXT PRIMARY KEY,\n    status TEXT NOT NULL,\n"
                   "    price_kopecks INTEGER\n);\n"),
    "utc_clock": ("app/subscriptions.py", None,
                  "\n\ndef _x():\n    from datetime import datetime\n    return datetime.now()\n"),
    "db_layer": ("app/subscriptions.py", None,
                 "\n\ndef _x(conn):\n    return conn.execute('SELECT 1')\n"),
    "app_error": ("app/subscriptions.py", None, "\n\ndef _x():\n    raise ValueError('x')\n"),
    "stdlib_only": ("app/subscriptions.py", None, "\n\ndef _x():\n    import requests\n"),
    "migrations": ("migrations/001_users.sql", None, "\n-- правка старой миграции\n"),
    "soft_delete": ("app/db.py", None,
                    "\n\ndef _x(conn):\n    conn.execute('DELETE FROM subscriptions')\n"),
    "uuid_id": ("migrations/009_extra.sql", None,
                "CREATE TABLE extra (\n    id INTEGER PRIMARY KEY,\n    status TEXT NOT NULL\n);\n"),
    "status_field": ("migrations/009_extra.sql", None,
                     "CREATE TABLE extra (\n    id TEXT PRIMARY KEY,\n    status TEXT NOT NULL,\n"
                     "    cancelled_at TEXT\n);\n"),
    "audit": ("app/subscriptions.py",
              '    db.add_audit(conn, "subscription", subscription_id, "cancelled", now)\n', ""),
    "log_event": ("app/subscriptions.py", None,
                  "\n\ndef _x():\n    log.info('subscription touched')\n"),
    "error_code": ("app/subscriptions.py", None,
                   "\n\ndef _x():\n    raise AppError('not_found', 'x')\n"),
}


def build(tmp: Path, round_dir: Path, with_reference: bool) -> Path:
    target = tmp / "p"
    shutil.copytree(round_dir / "project", target)
    if with_reference:
        shutil.copytree(round_dir / "reference", target, dirs_exist_ok=True)
    return target


def run_own_tests(project: Path) -> None:
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                   cwd=project, check=True, capture_output=True)


def mutate(project: Path, key: str) -> None:
    rel, old, new = MUTATIONS[key]
    path = project / rel
    if old is None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(new)
        return
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, key
    path.write_text(text.replace(old, new), encoding="utf-8")


def selftest_round(num: int, tmp: Path) -> list:
    round_dir = ROOT / "rounds" / str(num)
    keys = ROUNDS[num]

    def broken(project: Path) -> set:
        return set(broken_keys(check(project, round_dir / "project", keys)))

    failures = []
    base_broken = broken(build(tmp / "a", round_dir, False)) - DYNAMIC
    if base_broken:
        failures.append(f"исходный проект дает нарушения: {sorted(base_broken)}")
    ref = build(tmp / "b", round_dir, True)
    ref_broken = broken(ref)
    if ref_broken:
        failures.append(f"эталон дает нарушения: {sorted(ref_broken)}")
    try:
        run_own_tests(ref)
    except subprocess.CalledProcessError as err:
        failures.append("эталон не проходит свои тесты:\n" + err.stderr.decode())
    passed, total = acceptance(ref)
    if passed != total:
        failures.append(f"эталон проходит приемку {passed} из {total}")
    caught = 0
    for key in keys:
        project = build(tmp / f"c_{key}", round_dir, True)
        mutate(project, key)
        got = broken(project)
        if got == {key}:
            caught += 1
        else:
            failures.append(f"подложено {key}, поймано {sorted(got)}")
    print(f"круг {num}: {caught} из {len(keys)} подложенных нарушений пойманы точно")
    return [f"круг {num}: {f}" for f in failures]


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for num in ROUNDS:
            failures += selftest_round(num, Path(tmp) / str(num))
    for line in failures:
        print("FAIL", line)
    print("selftest:", "OK" if not failures else "ОШИБКИ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
