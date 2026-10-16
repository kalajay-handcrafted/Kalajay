# Employee image attachments

Team Members → Add / Edit has an optional image picker. Attach up to three
photos or supporting images per employee; previews appear before saving.
Save member commits both the employee details and image references. Edit a
member to remove a photo, then save. Directory thumbnails open full images.

Photos are converted to JPEG in the browser (maximum 1800 pixels on the longest
side), with a 1 MB limit per saved image. Files stay in the persistent private
KALAJAY_DATA_DIR/team-images directory. Only references are stored in the new
team_member_images table in the existing shared SQLite database. No employee
images or personal data are committed to source or exposed in the public
website catalogue; the website's aggregate member count is unchanged by an
image-only edit.

Backend initialization creates before-team-images.sqlite3 before the additive
schema migration. Existing employee rows and counting rules are retained.
Image reads require ERP login. Admin-only, same-origin member writes remain
enforced. Reference validation is scoped to the employee. A stale image list
is rejected rather than deleting attachments saved in another session. Old
clients omitting images preserve all existing attachments.

Removing an attachment removes its record reference, not the immutable disk
file, so historical backups remain usable. Back up both SQLite and team-images.
No production employee/test records are added during verification.

Validation: python3 -m unittest -v test_team_images test_expenses (from Final).
Tests use temporary databases and cover upload/read/removal, count preservation,
legacy edits, member reference isolation, malformed files and size/count limits,
concurrent attachment edits, authentication, view-only managers and CSRF.
