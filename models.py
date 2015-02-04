from google.appengine.ext import db

class User(db.Model):
  id = db.StringProperty(required=True)
  created = db.DateTimeProperty(auto_now_add=True)
  updated = db.DateTimeProperty(auto_now=True)
  name = db.StringProperty(required=True)
  profile_url = db.StringProperty(required=True)
  access_token = db.StringProperty(required=True)
  offline_token = db.StringProperty(required=False)
  offline_token_created = db.DateTimeProperty(required=False)
  offline_token_expires = db.DateTimeProperty(required=False)

class UserPrefs(db.Model):
  location_lat = db.FloatProperty(default=0.0,required=False)
  location_lng = db.FloatProperty(default=0.0,required=False)
  location_name = db.StringProperty(default="",required=False)
  search_lat = db.FloatProperty(default=0.0,required=False)
  search_lng = db.FloatProperty(default=0.0,required=False)
  search_name = db.StringProperty(default="",required=False)
  acknowledged_terms = db.BooleanProperty(default=False,required=False)

def get_userprefs(user_id):
  key = db.Key.from_path('UserPrefs', user_id)
  userprefs = db.get(key)
  if not userprefs:
    userprefs = UserPrefs(key_name=user_id)
  return userprefs
