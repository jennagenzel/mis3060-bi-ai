import csv

FILE_PATH = "02_Data/raw/fact_transactions.csv"

def count_buy_transactions(file_path: str) -> int:
    """Count rows in fact_transactions.csv where txn_type is exactly 'Buy'."""
    count = 0
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["txn_type"] == "Buy":
                count += 1
    return count


if __name__ == "__main__":
    total = count_buy_transactions(FILE_PATH)
    print(f"Number of 'Buy' transactions: {total}")
