from google.appengine.ext import db

class UserPrefs(db.Model):
  tz_offset = db.IntegerProperty(default=0)
  location = db.StringProperty(default="")

def get_userprefs(user_id):
  key = db.Key.from_path('UserPrefs', user_id)
  userprefs = db.get(key)
  if not userprefs:
    userprefs = UserPrefs(key_name=user_id)
  return userprefs
