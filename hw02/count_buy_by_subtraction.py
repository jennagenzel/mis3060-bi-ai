import csv

FILE_PATH = "02_Data/raw/fact_transactions.csv"

EXCLUDED_TYPES = {"Sell", "Deposit", "Withdrawal", "Dividend", "Advisory Fee"}


def count_buy_by_subtraction(file_path: str) -> tuple[int, int, int]:
    """Count total rows, then subtract rows whose txn_type is one of the
    excluded types (Sell, Deposit, Withdrawal, Dividend, Advisory Fee).

    Returns (total_rows, excluded_rows, remaining_rows).
    """
    total_rows = 0
    excluded_rows = 0
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            if row["txn_type"] in EXCLUDED_TYPES:
                excluded_rows += 1
    remaining_rows = total_rows - excluded_rows
    return total_rows, excluded_rows, remaining_rows


if __name__ == "__main__":
    total, excluded, remaining = count_buy_by_subtraction(FILE_PATH)
    print(f"Total rows: {total}")
    print(f"Excluded rows (Sell/Deposit/Withdrawal/Dividend/Advisory Fee): {excluded}")
    print(f"Remaining rows (should equal 'Buy' count): {remaining}")
