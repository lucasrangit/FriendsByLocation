from google.appengine.ext import db

class UserPrefs(db.Model):
  location_lng = db.FloatProperty(default=0.0,required=False)
  location_lat = db.FloatProperty(default=0.0,required=False)
  location_name = db.StringProperty(default="",required=False)
  search_lng = db.FloatProperty(default=0.0,required=False)
  search_lat = db.FloatProperty(default=0.0,required=False)

def get_userprefs(user_id):
  key = db.Key.from_path('UserPrefs', user_id)
  userprefs = db.get(key)
  if not userprefs:
    userprefs = UserPrefs(key_name=user_id)
  return userprefs
