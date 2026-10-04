from pathlib import Path
rows = [('A',30),('B',7.5)]
Path(build_output_path('codeact-sales.csv')).write_text('category,amount\nA,30\nB,7.5\n')
print(sum(r[1] for r in rows))