Update our user/account management system with the following requirements:

1. **Signup Form Changes**
   - Add a new `phone_number` field to the signup form.
   - Phone number should only accept digits (6–15 digits) and be validated on both frontend and backend.
   - Store `phone_number` in the database as part of the user record.

2. **Database Updates**
   - Add a new column `phone_number` to the users table. Ensure migration is handled correctly with Alembic.
   - Keep existing fields: `org_name`, `email`, `password`.
   - Any existing data should not break.

3. **Settings Page**
   - Display `org_name`, `email`, and `phone_number`.
   - `org_name` should appear as "Company Name" in the UI and should be greyed out (non-editable for now to avoid clashes).
   - `email` and `phone_number` should be editable.
   - Include a "Save" button that updates only the editable fields in the database.
   - Changes should persist in the database and update the UI dynamically.

4. **Account Info Component**
   - Create a shared component for displaying logged-in user information and the logout button.
   - Store this component centrally in `app/ui/shared` so it can be reused.
   - Replace the top-of-page account information on `dashboard.html` with this component.
   - Place the component at the bottom of the left pane in `dashboard.html`, above the logout button.
   - Include it in `settings.html` so user info and logout are accessible on multiple pages.

5. **Frontend Requirements**
   - Inputs for email and phone should have proper validation (phone digits only).
   - Display current values from the database when the page loads.
   - Clicking "Save" should send updated data to the backend and update the database.
   - Greyed-out `org_name` should not be editable.
   - Show success/failure messages after updates.

6. **Backend Requirements**
   - Ensure proper validation on phone number and email.
   - Update endpoints to handle fetching and updating `phone_number` along with email.
   - Existing user records without a phone number should not break the application.
   - Ensure cursor/SQLAlchemy/Alembic integration is correct and migrations are included.

7. **Additional Notes**
   - Make sure the shared account info component can be reused on any page.
   - Ensure logout functionality works from both `dashboard.html` and `settings.html`.
   - The system should be consistent and maintain current UX while adding phone number support.
