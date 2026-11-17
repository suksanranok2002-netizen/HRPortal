HR MASTER PORTAL - INSTALLATION GUIDE FOR IT (WINDOWS)
=======================================================

WHAT THIS IS
  A web page (Employee Register, Contracts, Children, Warnings, Appraisals, Promotions, Certificates)
  with a small server and a SQLite database. All data is saved on this computer in hr_portal.db.
  No internet access is needed at runtime. No extra packages are needed (Python standard library only).

REQUIREMENTS
  - Windows 10 / 11 or Windows Server 2016+
  - Python 3.9 or newer from python.org. During setup tick "Install for all users" and "Add python.exe to PATH".

INSTALL (about 5 minutes)
  1. Copy the whole HRPortal folder to the server, for example C:\HRPortal
  2. Double-click start.bat. A console window opens and shows:
       "Database created and imported from seed.json"
     The first start creates hr_portal.db and imports the employee data from the Excel file (seed.json).
     A line "WARNING: duplicate Emp ID skipped" means the Excel file had two rows with the same Emp ID
     (E01791); only the first row was imported. Please check that record.
  3. Open http://localhost:8080 on the server. From other PCs use http://SERVERNAME:8080
  4. For automatic start, firewall rule and a daily backup at 22:00: right-click install_task.bat ->
     Run as administrator. (To use another port, edit PORT in start.bat and the port in install_task.bat.)

DATA AND BACKUP
  - Database file: hr_portal.db (SQLite). Tables: employees, contracts, children, warnings, promotions,
    certificates, appraisals, lists (branch / department / position), audit_log (time, client IP, action).
  - backup.bat makes a safe copy into the backups folder (keeps the newest 30). Copy that folder to another
    machine or a network share regularly.
  - To restore: stop the server, replace hr_portal.db with a backup copy, start again.
  - To re-import from the Excel data: stop the server, delete hr_portal.db (and the .db-wal / .db-shm files), start again.
    WARNING: this erases everything entered since.
  - The database can be opened with any SQLite tool (for example DB Browser for SQLite) for reports.

SECURITY - PLEASE READ
  - This version has NO login (as requested). Anyone who can reach the server address can read and change all data,
    including personal data and bank account numbers.
  - Recommended: allow the port only from HR computers (Windows Firewall scope / network ACL), or put the portal
    behind IIS (URL Rewrite + Application Request Routing) with Windows Authentication and HTTPS.
  - Restrict NTFS permissions on this folder (and backups) to administrators and the service account.
  - The portal is meant for a small number of users on the internal network.

API (JSON) - for IT reference
  GET    /api/data                 all data
  PUT    /api/employee/<EmpID>     create or update an employee   body {"row":[24 values]}
  POST   /api/<kind>               add a record                   body {"row":[...]}   returns {"rid":n}
  PUT    /api/<kind>/<rid>         update a record
  DELETE /api/<kind>/<rid>         delete a record
  PUT    /api/lists                body {"dept":[],"branch":[],"pos":[]}
  kind = con (contracts), kids (children), warn (warnings), prom (promotions), cert (certificates), appr (appraisals)
  Column order for every table is defined at the top of server.py.

LIMITS
  - Max 5 children per employee (checked by the page and by the server).
  - Employees cannot be deleted from the page; set Working Status to Resigned instead.
  - The page draws all rows at once. It is smooth for a few hundred employees; for several thousand,
    add paging before use.
  - Tested on Linux with Python 3.12 (API and page logic). Not tested on a Windows server - please test
    start.bat and install_task.bat on a test machine first.
