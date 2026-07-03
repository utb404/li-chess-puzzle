"""
Скрипт для скачивания базы задач lichess и отбора самых популярных.

Скачивает полную базу задач (https://database.lichess.org/#puzzles),
выбирает 500 самых популярных задач (по количеству попыток NbPlays)
и сохраняет их в puzzles.csv в корне проекта.

Использование:
    pip install requests zstandard
    python scripts/download_puzzles.py

Скачивается ~250 МБ, распаковка идет потоково — файл на диск
целиком не сохраняется.
"""
import csv
import heapq
import io
import sys
from pathlib import Path

import requests
import zstandard

PUZZLES_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
TOP_COUNT = 500
OUTPUT_FILE = Path(__file__).parent.parent / "puzzles.csv"


def main() -> None:
    print(f"Скачивание базы задач: {PUZZLES_URL}")
    response = requests.get(PUZZLES_URL, stream=True, timeout=60)
    response.raise_for_status()

    decompressor = zstandard.ZstdDecompressor()
    stream = decompressor.stream_reader(response.raw)
    text_stream = io.TextIOWrapper(stream, encoding='utf-8')

    reader = csv.reader(text_stream)
    header = next(reader)

    try:
        plays_index = header.index('NbPlays')
    except ValueError:
        print(f"Колонка NbPlays не найдена. Заголовок: {header}", file=sys.stderr)
        sys.exit(1)

    def plays(row):
        try:
            return int(row[plays_index])
        except (ValueError, IndexError):
            return 0

    print("Отбор самых популярных задач (это займет несколько минут)...")
    top_rows = heapq.nlargest(TOP_COUNT, reader, key=plays)
    top_rows.sort(key=plays, reverse=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(top_rows)

    print(f"Готово: {len(top_rows)} задач сохранено в {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
