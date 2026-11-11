Mollick Krishi Bhandar Create User Password Validation - Corrected

Create User passwords must:
- Have at least 8 characters
- Include at least one English letter (A-Z or a-z)
- Include at least one digit (0-9)
- Include at least one special character (for example @, #, $, !)
- Contain no spaces or other whitespace

Validation is implemented in both the browser form and the FastAPI POST /create-user handler.
Changed files: app/main.py and templates/create_user.html.

IMPORTANT: Back up the current project first. Stop the server. Extract this ZIP and copy the CONTENTS of the inner benfed_fastapi_login folder into your existing project folder, preserving the app and templates folders. Replace files when prompted. Then restart run_8080.bat. Do not extract into an extra nested benfed_fastapi_login folder.
