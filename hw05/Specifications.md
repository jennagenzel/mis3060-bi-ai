# Script to Verify Keys and Grains (Parts A and B)

Create me a script called checks_keys.py in my hw05 folder that does or verifies the following:

- every primary key is unique and never blank (Part A)
- every foreign key matches its target table, with security_id blanks allowed only on cash transactions (Part A)
- fact dates match dim_date[date] (Part A)
- each fact table’s grain is unique: one row per client per month for fees and for snapshots, and one row per txn_id for transactions (Part B)