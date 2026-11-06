# Repository conventions

- Python 3.11+ with standard-library-only runtime. Run from source with `python3 -m explabs`.
- Run `python3 -m unittest discover -s tests -v` and `python3 -m explabs --help` after changes.
- Keep HTTPS/API transport, report logic, and presentation separate so a future portal can reuse the report service server-side.
- Monetary arithmetic uses Decimal; JSON USD amounts are decimal strings. Never infer missing money or quotas as zero.
- Never commit credentials, dotenv files other than the placeholder example, or real account reports.
- API operations are read-only. Do not add inference calls or account mutations to a usage report.
