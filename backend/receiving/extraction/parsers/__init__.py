"""Built-in parsers. Importing this package registers them all.

Adding a vendor format means adding one module here (a layout plus a registered
function) and importing it below; nothing downstream changes.
"""

from . import invoice_json, v01_thistlewood_csv, v05_lucentara_csv, v06_halvorsen_csv  # noqa: F401
