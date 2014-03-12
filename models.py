from google.appengine.ext import db

class UserPrefs(db.Model):
  #location = db.StringProperty(default="")
  location_id = db.IntegerProperty(default=0,required=False)

def get_userprefs(user_id):
  key = db.Key.from_path('UserPrefs', user_id)
  userprefs = db.get(key)
  if not userprefs:
    userprefs = UserPrefs(key_name=user_id)
  return userprefs
