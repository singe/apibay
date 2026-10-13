# apibay CLI

A small Python command-line tool for searching apibay.org, viewing an entry's details and files, and generating a magnet link.

## Requirements

- Python 3.7 or newer
- Internet access to apibay.org

The script uses only Python's standard library; there are no packages to install.

## Usage

Run commands from this directory:

```sh
./apibay.py search "the last starfighter"
./apibay.py search --columns uploader "the last starfighter"
./apibay.py search the last starfighter
./apibay.py details 83808736
./apibay.py magnet 83808736
```

## Output

`search` results show the ID, size, seeders/leechers, date added, and name. Dates use `DD/MM/YY` in the machine's local timezone. It tries to be smart with padding. Pass `--columns uploader` to append the uploader name; unavailable names display as `-`.
`details` begins with the same summary layout, followed by the description and a tab-separated list of file names and sizes.
`magnet` prints a magnet URI for the entry.

Search and details use terminal colors when writing to an interactive terminal. Colors are disabled when output is redirected or `NO_COLOR` is set. API-provided text is filtered for terminal escape sequences and control characters before display.
