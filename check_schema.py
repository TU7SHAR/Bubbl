import psycopg2

conn = psycopg2.connect(
    'postgresql://neondb_owner:npg_VFGr5R0HqjbX@ep-rapid-rain-a1k0u5dn-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'
)
cur = conn.cursor()
cur.execute("""
    SELECT table_name, column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position
""")
cur_table = None
for row in cur.fetchall():
    if row[0] != cur_table:
        cur_table = row[0]
        print()
        print('--- ' + cur_table + ' ---')
    nd = 'NULL' if row[3] == 'YES' else 'NOT NULL'
    df = (' DEFAULT ' + str(row[4])) if row[4] else ''
    print('  ' + row[1].ljust(35) + row[2].ljust(22) + nd + df)
conn.close()
