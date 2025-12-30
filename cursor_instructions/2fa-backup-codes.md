Write a secure Python function to generate 2FA backup codes for a user and store them encrypted in the database. Present these codes to the user upon enabling 2FA after the user successfully enters both required MFA codes to enable MFA.


Requirements:  

1. Generate 10 random backup codes, each 8 characters long, using letters and digits.  
2. Encrypt each backup code using a secure symmetric encryption method before storing in the database.  
3. Store the encrypted codes in a table linked to the user, including fields for `user_id`, `encrypted_code`, and a `consumed` boolean flag.  
4. Return the plaintext codes to the API so the user can store them safely, but do not log them anywhere.  
5. Ensure backup codes are one-time use; when a code is used, mark it as consumed in the database.  
6. Integrate with a Flask endpoint that is called after TOTP 2FA is successfully enabled, returning the codes to the user in the JSON response.  
7. Follow secure coding best practices: handle database sessions correctly, avoid exposing secrets, and prevent replay attacks.  
8. Use SQLAlchemy ORM for database interactions.  
9. If the user disables 2FA, wipe the backup codes from the DB related to that MFA code
10. Create a python script I can run where I can input the user_id to retrieve the backup 2FA codes should the user become locked out and need admin intervention.

Generate complete, production-ready code including imports, function definition, and example usage in a Flask route.
