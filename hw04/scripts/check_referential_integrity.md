# Reusable function: `check_referential_integrity`

From `hw04/scripts/03_validate.py` (Assignment 4) - saved for reuse in Assignment 5.

## Code

```python
import pandas as pd


def check_referential_integrity(fact_df, fact_key, dim_df, dim_key):
    """Check that every value of fact_df[fact_key] exists in dim_df[dim_key].

    Keys are compared exactly as stored text after trimming spaces - the same
    way a BI tool joins - so '45.0' does NOT match '45'. Read both tables with
    dtype=str, keep_default_na=False.

    Returns a dict:
        match_rate           share of NON-blank keys found in the dimension (0-1)
        orphan_rows          DataFrame of fact rows whose non-blank key is missing
        distinct_orphan_keys sorted list of the missing key values
        null_key_rate        share of fact rows whose key is blank (0-1)
        n_rows, n_non_null, n_orphan_rows   counts behind the rates
    """
    fk = fact_df[fact_key].astype(str).str.strip()
    pk = set(dim_df[dim_key].astype(str).str.strip())
    is_null = fk.isin(["", "nan", "NaN", "None", "NULL", "null"])
    non_null = ~is_null
    orphan = non_null & ~fk.isin(pk)
    n, n_nn = len(fk), int(non_null.sum())
    keys = fk[orphan].unique().tolist()
    try:
        keys = sorted(keys, key=float)
    except ValueError:
        keys = sorted(keys)
    return {
        "match_rate": (n_nn - int(orphan.sum())) / n_nn if n_nn else 1.0,
        "orphan_rows": fact_df[orphan],
        "distinct_orphan_keys": keys,
        "null_key_rate": int(is_null.sum()) / n if n else 0.0,
        "n_rows": n,
        "n_non_null": n_nn,
        "n_orphan_rows": int(orphan.sum()),
    }
```

## Example

```python
fact = pd.read_csv('fact_fees.csv', dtype=str, keep_default_na=False)
dim = pd.read_csv('dim_client.csv', dtype=str, keep_default_na=False)
r = check_referential_integrity(fact, 'client_id', dim, 'client_id')
print(f"match {r['match_rate']:.1%}, orphans {r['n_orphan_rows']}, "
      f"keys {r['distinct_orphan_keys'][:5]}, null {r['null_key_rate']:.1%}")
r['orphan_rows'].to_csv('orphans.csv', index=False)   # inspect the failing rows
```

## Notes

- Keys are compared as trimmed text, the way a BI tool joins; `'45.0'` does not match `'45'`.
- `match_rate` is computed over non-blank keys; blanks are reported separately as `null_key_rate`.
- For a date relationship pass the date columns, e.g. `check_referential_integrity(fees, 'fee_date', dim_date, 'date')`.
