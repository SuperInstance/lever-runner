# Data Skill Pack — 20 Commands

```yaml
# File Search & Text Processing
- intent: "find files by name {{pattern}}"
  command: "find . -name \"{{pattern}}\" -type f"
  tags: [data, find, search]

- intent: "find files modified in last {{days}} days"
  command: "find . -mtime -{{days}} -type f"
  tags: [data, find, recent]

- intent: "find large files over {{size}}"
  command: "find . -size +{{size}} -type f -exec ls -lh {} +"
  tags: [data, find, large]

- intent: "search for {{pattern}} in files"
  command: "grep -r \"{{pattern}}\" . --include=\"*.{py,js,ts,rs}\" -n"
  tags: [data, grep, search]

- intent: "search for {{pattern}} case insensitive"
  command: "grep -ri \"{{pattern}}\" . -n"
  tags: [data, grep, search, case-insensitive]

- intent: "show lines matching {{pattern}} with context"
  command: "grep -B2 -A2 \"{{pattern}}\" {{file}}"
  tags: [data, grep, context]

- intent: "extract column {{n}} from file"
  command: "awk '{print ${{n}}}' {{file}}"
  tags: [data, awk, column]

- intent: "sum column {{n}} from file"
  command: "awk '{sum += ${{n}}} END {print sum}' {{file}}"
  tags: [data, awk, sum]

- intent: "replace text in file"
  command: "sed -i 's/{{old}}/{{new}}/g' {{file}}"
  tags: [data, sed, replace]

- intent: "show first {{n}} lines of file"
  command: "head -n {{n}} {{file}}"
  tags: [data, head, preview]

- intent: "show last {{n}} lines of file"
  command: "tail -n {{n}} {{file}}"
  tags: [data, tail, preview]

- intent: "follow file output"
  command: "tail -f {{file}}"
  tags: [data, tail, follow]

# JSON Processing
- intent: "format json file"
  command: "jq '.' {{file}}"
  tags: [data, jq, format]

- intent: "extract key from json"
  command: "jq '.{{key}}' {{file}}"
  tags: [data, jq, extract]

- intent: "filter json array"
  command: "jq '.[] | select(.{{field}} == \"{{value}}\")' {{file}}"
  tags: [data, jq, filter]

- intent: "count json array items"
  command: "jq '. | length' {{file}}"
  tags: [data, jq, count]

- intent: "extract keys from json"
  command: "jq 'keys' {{file}}"
  tags: [data, jq, keys]

- intent: "pretty print yaml with yq"
  command: "yq '.' {{file}}"
  tags: [data, yq, format]

- intent: "extract value from yaml"
  command: "yq '.{{path}}' {{file}}"
  tags: [data, yq, extract]

# CSV Processing
- intent: "show csv headers"
  command: "head -1 {{file}} | tr ',' '\\n'"
  tags: [data, csv, headers]

- intent: "cut csv column {{n}}"
  command: "cut -d',' -f{{n}} {{file}}"
  tags: [data, csv, column]

- intent: "sort csv by column {{n}}"
  command: "sort -t',' -k{{n}} {{file}}"
  tags: [data, csv, sort]

- intent: "count csv rows"
  command: "wc -l {{file}}"
  tags: [data, csv, count]

- intent: "filter csv rows with csvgrep"
  command: "csvgrep -c {{col}} -m \"{{pattern}}\" {{file}}"
  tags: [data, csv, filter]

- intent: "show csv summary with miller"
  command: "mlr --csv stats1 -a count,mean,stddev -f {{field}} {{file}}"
  tags: [data, csv, miller, stats]

# Database
- intent: "query sqlite database"
  command: "sqlite3 {{db}} \"{{query}}\""
  tags: [data, sqlite, query]

- intent: "show sqlite tables"
  command: "sqlite3 {{db}} \".tables\""
  tags: [data, sqlite, tables]

- intent: "show sqlite schema for {{table}}"
  command: "sqlite3 {{db}} \".schema {{table}}\""
  tags: [data, sqlite, schema]

- intent: "query postgres"
  command: "psql -c \"{{query}}\" {{db}}"
  tags: [data, postgres, query]

- intent: "list postgres databases"
  command: "psql -l"
  tags: [data, postgres, list]

- intent: "show postgres tables"
  command: "psql -c \"\\dt\" {{db}}"
  tags: [data, postgres, tables]

- intent: "query mysql"
  command: "mysql -e \"{{query}}\" {{db}}"
  tags: [data, mysql, query]

- intent: "show mysql databases"
  command: "mysql -e \"SHOW DATABASES;\""
  tags: [data, mysql, list]
```
