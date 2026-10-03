# Manual sign-up test walkthrough

One new user account from start to finish: sign up, login, logout, forgot password, admin reset, and cleanup. Runs on **staging.racinglines.bet** before the weekend (book Fri 2 Oct 03:30Z to Sun 7 Oct 07:00Z); production **racinglines.bet** only after the book closes unless the owner says otherwise.

Browser setup: max width **1024 px** at **150% zoom** (for screenshots, use Playwright viewport `{"width": 683, "height": 900}, device_scale_factor=1.5`). Have a second browser tab open to `/admin/users` as `admin` (demo login) to reset the test user's password and clean up at the end.

## Step 1: Load the signup page

**Go to:** `https://staging.racinglines.bet/signup`

**Expected:** The sign-up card shows a form with fields for Username, Password, Password again. The form says "Create your beta account" and mentions "1,000 fantasy bucks" and "pro tier".

**Fail if:** The page says "Sign-up isn't open yet" (check `/admin/users` that the accounts ledger exists: `racinglines users setup` must have run on the VM). Or 404.

**Screenshot:** Full signup form.

## Step 2: Enter invalid username, check feedback

**Do:** In the Username field, type `test`, then tab out.

**Expected:** An error appears below the field: "Usernames are 3 to 30 characters: lower-case letters, digits, '.', '_' or '-', starting with a letter or digit." (Username is too short.)

**Fail if:** No error, or a different error message.

## Step 3: Enter a valid new username

**Do:** Clear Username and type `testuser1` (adjust the number if this username was already taken in a previous run).

**Expected:** The error clears.

**Fail if:** Error persists (the username may be reserved or taken; try `testuser2`, etc.).

## Step 4: Enter password

**Do:** In Password, type a password with at least 10 characters, e.g. `TestPass123`. In Password again, type the same.

**Expected:** Both fields fill. No error.

**Fail if:** Error about password length (must be at least 10 characters).

## Step 5: Check the adult checkbox and submit

**Do:** Check the checkbox "I'm 18 or older, and I understand this is a beta that uses fantasy money only." Then click **Create account**.

**Expected:** The page redirects to the Markets board (likely `/markets/polymarket` or the first enabled exchange). You see a list of race events/markets. The page title is "racinglines" and you are logged in.

**Fail if:** Form error (e.g. "passwords don't match"), 500 error, or redirect to `/login` (signup may have failed silently; check step 2's error and try a different username). Or a 429 if the IP has made too many signup attempts (10 per hour limit).

**Screenshot:** Markets board after signup, showing you are signed in (no login button, likely a logout link somewhere).

## Step 6: Log out

**Do:** Find and click the logout button or link (likely in the top right or a menu). It may say "Logout" or "Sign out".

**Expected:** You are redirected to `/login`. The page shows "Try as pro" and "Try as basic" demo buttons and a sign-in form.

**Fail if:** You are still on the Markets page or an error. Check that a logout route exists (`/logout`).

**Screenshot:** Login page after logout.

## Step 7: Try wrong password

**Do:** On the login form, enter username `testuser1` (or your test username) and an incorrect password like `WrongPass123`. Click **Sign in**.

**Expected:** You stay on `/login` and see a red error message "Wrong username or password."

**Fail if:** You are logged in (the username or password check is broken). Or you see a 429 error after 8 failed logins within 15 minutes (correct behavior; wait 15 min and retry).

## Step 8: Log in with correct credentials

**Do:** Enter username `testuser1` and the correct password from step 4. Click **Sign in**.

**Expected:** You are logged in and redirected to the Markets board.

**Fail if:** "Wrong username or password" error. The password may have been stored incorrectly at signup; go to step 11 (admin reset).

**Screenshot:** Markets board after login.

## Step 9: Navigate the app

**Do:** Click through the following pages (they should load without 500 errors or broken links):
1. The Markets page itself (you are here).
2. Check for a "Positions" or "P&L" page (old route: `/me` → `/positions`). If it exists, open it.
3. Look for a profile, settings, or account menu that shows your fantasy bucks balance (currently displayed only in `/admin/users` for now; checking this is UNKNOWN if the balance appears in the user-facing UI).

**Expected:** No 404s or 500 errors. Pages load and show content (markets, positions, profile, etc.).

**Fail if:** 404 on any page. 500 errors. Or dead links (e.g. links to Events or Athletes pages, which were removed in round 2 but may still appear in navigation).

**Screenshot:** Markets page, and any Positions/P&L page if it exists.

## Step 10: Went to the forgot password page (optional, for coverage)

**Do:** Log out (step 6 again). Go to `https://staging.racinglines.bet/forgot`.

**Expected:** A card with title "Forgot your password?" and a form that asks for your username and shows a pre-filled email template to send to `hello@racinglines.bet`.

**Fail if:** 404 (sign-up may not be enabled). The email template is missing or shows the wrong address.

**Screenshot:** Forgot password page.

## Step 11: Admin reset the password

**Do:** Log in as `admin` with password `password` (demo login) to `/admin/users`. Find your test user (`testuser1`) in the Accounts table. Click the **Reset password** button in that row.

**Expected:** The page refreshes. A message appears at the top: "Password reset for testuser1." Below the table, a box shows the username and a one-time temporary password (e.g. `Xy_Z1a2bCd3eF-g`).

**Fail if:** 404 on /admin/users. User not in the table. Button missing. Or a message about user history (the user has trades; cleanup must happen first; go to step 12).

**Screenshot:** Admin users page showing the one-time password.

## Step 12: Log in with the temporary password

**Do:** Log out from the admin account. Go to `/login`. Log in as `testuser1` with the temporary password from step 11.

**Expected:** You are logged in and taken to the Markets board.

**Fail if:** "Wrong username or password" error. The temp password may have expired or not been stored correctly.

## Step 13: Check fantasy bucks balance (UNKNOWN)

**Do:** Look for a balance display on the Markets page, user profile, or account settings. It should show 1,000 (the signup grant).

**Expected:** Somewhere on the app, your balance is shown as 1,000 or 1,000.00 fantasy bucks.

**Fail if:** Balance is not displayed anywhere in the user-facing UI (currently it is only in `/admin/users` for admins; this feature is UNKNOWN for regular users).

**Note:** This step may not have a user-facing path yet; the balance is confirmed to exist in the database (checked in `/admin/users`).

## Step 14: Cleanup - delete or deactivate the test user

**Do:** Log out. Log in as `admin` again. Go to `/admin/users`. Find `testuser1` in the table.

**Expected:** You see the user in the Accounts table with columns for User, Role, Active, Last seen, Markets, Bets placed, etc.

**Options:**

**Option A: Delete (if the user has no history)**
1. In the same row, click **Delete**.
2. A confirmation may appear. Confirm.

**Expected:** The user is removed from the table. A message says "Deleted testuser1."

**Fail if:** An error says "Can't delete" or "has history"; the user has placed bets or made markets. Use Option B instead.

**Option B: Deactivate (safe, keeps history)**
1. In the same row, find the Active checkbox and uncheck it.
2. Click **Update**.

**Expected:** The user is marked inactive. A message says "Updated testuser1." The Active column now shows unchecked for this user.

**Fail if:** The user is still active.

**Screenshot:** Admin users page after deletion or deactivation, showing `testuser1` is gone or marked inactive.

## Summary

| Step | Coverage |
|------|----------|
| 1–5 | Signup form validation and account creation |
| 6 | Logout |
| 7 | Wrong password throttle (after 8 failures, 429 for 15 min) |
| 8–9 | Login and app navigation |
| 10 | Forgot password page (optional) |
| 11–12 | Admin password reset and temp login |
| 13 | Fantasy bucks balance (UNKNOWN if user-facing) |
| 14 | User cleanup |

**Known unknowns:**
- Step 13: Fantasy bucks balance is stored in the `accounts.fantasy_ledger` table but may not display in the user app yet (currently visible in `/admin/users` only).
- Forgot password flow (step 10) is manual: the user writes to `hello@racinglines.bet` and an admin replies with a temp password (this walkthrough does that in step 11).
- After signup, the redirect goes to `/markets` which may route to `/markets/polymarket` or the first enabled exchange; verify the exact behavior in your session.

**Clean up after:** Delete or deactivate the test user (step 14) so the account list stays clean for future tests.
