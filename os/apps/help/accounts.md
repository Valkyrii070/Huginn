# Online Accounts
Sign in once, and Mail, Calendar, Contacts and Files use the account. It's in Settings.

## Add an account
Choose Google, Microsoft, iCloud or Nextcloud. Google and Microsoft open their own sign-in page in Huginn: Settings never sees your password. Nextcloud does the same and gives this computer a password of its own, which you can revoke from your Nextcloud. iCloud needs an app-specific password: make one on appleid.apple.com, under Sign-In and Security.

## Choose what it's for
Each account has switches for Mail, Calendars, Contacts and (Nextcloud) Files. Turn one off and that part leaves this computer; nothing on the account itself changes.

## Calendars
Events show in Calendar in the account's colours. Change an event's name, day or time in Calendar and the change goes back to the account; only those parts change there, so people you invited and reminders stay as they were. Delete an event and it's deleted on the account too.

## Contacts
People from the account show in Contacts and are kept in step with it. Change them at the source; Contacts brings the change down.

## Keeping in step
Accounts are kept up to date every 15 minutes while you're signed in, and Passwords is unlocked. Sync Now does it at once.

## Where sign-ins are kept
In Passwords, under your master password, never on disk in the clear. If Passwords is locked, Online Accounts asks you to unlock it.

## Not registered yet?
Google and Microsoft only let an app use their sign-in page once it's registered with them (free, done once by whoever builds this copy of Huginn OS). Until then their tiles say so; iCloud and Nextcloud work regardless. The registration goes in /etc/huginn/mail-oauth.json.
