import datetime
import facebook
import jinja2
import models
import os
import webapp2
import urllib2

# Store your Facebook app ID, API key, etc... in a file named secrets.py, which
# is in .gitignore to protect the innocent.
import secrets
FACEBOOK_APP_ID = secrets.FACEBOOK_APP_ID
FACEBOOK_APP_SECRET = secrets.FACEBOOK_APP_SECRET

import logging
logging.getLogger().setLevel(logging.DEBUG)

from google.appengine.ext import db
from webapp2_extras import sessions

config = {}
config['webapp2_extras.sessions'] = dict(secret_key='')

template_env = jinja2.Environment(
  loader=jinja2.FileSystemLoader(os.path.join(os.getcwd(),'templates')))


class User(db.Model):
    id = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)
    name = db.StringProperty(required=True)
    profile_url = db.StringProperty(required=True)
    access_token = db.StringProperty(required=True)

class Friend():
    def __init__(self, id, name, link, location):
        self.id = id
        self.name = name
        self.link = link
        self.location = location
        
    def __str__(self):
        return "%s (%s)" % (self.name, self.id)
        
class BaseHandler(webapp2.RequestHandler):
    """Provides access to the active Facebook user in self.current_user

    The property is lazy-loaded on first access, using the cookie saved
    by the Facebook JavaScript SDK to determine the user ID of the active
    user. See http://developers.facebook.com/docs/authentication/ for
    more information.
    """
    @property
    def current_user(self):
        if self.session.get("user"):
            # User is logged in
            logging.info("User is logged in.")
            return self.session.get("user")
        else:
            # To workaround "HTTPError: HTTP Error 400: Bad Request" 
            # in get_access_token_from_code() uncomment:
            #return None
            logging.info("Check if user is logged in.")
            # Either used just logged in or just saw the first page
            # We'll see here
            cookie = facebook.get_user_from_cookie(self.request.cookies,
                                                   FACEBOOK_APP_ID,
                                                   FACEBOOK_APP_SECRET)
            if cookie:
                # Okay so user logged in.
                # Now, check to see if existing user
                user = User.get_by_key_name(cookie["uid"])
                logging.info("Cookie found, user is logged in.")
                if not user:
                    # Not an existing user so get user info
                    graph = facebook.GraphAPI(cookie["access_token"])
                    
                    profile = graph.get_object("me")
                    
                    user = User(
                        key_name=str(profile["id"]),
                        id=str(profile["id"]),
                        name=profile["name"],
                        profile_url=profile["link"],
                        access_token=cookie["access_token"],
                    )
                    user.put()
                elif user.access_token != cookie["access_token"]:
                    user.access_token = cookie["access_token"]
                    user.put()
                # User is now logged in
                self.session["user"] = dict(
                    name=user.name,
                    profile_url=user.profile_url,
                    id=user.id,
                    access_token=user.access_token
                )
                return self.session.get("user")
        logging.info("No user logged in.")
        return None

    def dispatch(self):
        """
        This snippet of code is taken from the webapp2 framework documentation.
        See more at
        http://webapp-improved.appspot.com/api/webapp2_extras/sessions.html

        """
        self.session_store = sessions.get_store(request=self.request)
        try:
            webapp2.RequestHandler.dispatch(self)
        finally:
            self.session_store.save_sessions(self.response)

    @webapp2.cached_property
    def session(self):
        """
        This snippet of code is taken from the webapp2 framework documentation.
        See more at
        http://webapp-improved.appspot.com/api/webapp2_extras/sessions.html

        """
        return self.session_store.get_session()


class MainPage(BaseHandler):
        
  def get(self):
    user = self.current_user
    locations = dict()
    friends_count = 0
    if user:
      graph = facebook.GraphAPI(user["access_token"])
      # friends_of_friends = graph.fql("SELECT uid, name FROM user WHERE uid IN (SELECT uid2 FROM friend WHERE uid1 IN (SELECT uid FROM user WHERE uid IN (SELECT uid2 FROM friend WHERE uid1 = me() ) and is_app_user=1))")	
      friends = graph.fql("SELECT uid, name, current_location FROM user WHERE uid IN (SELECT uid1 FROM friend WHERE uid2 = me())")	
      #logging.info(friends)
      
      for profile in friends['data']:
        #logging.info(profile)
        friends_count += 1
        if not profile['current_location']:
          continue
        else:
          location_id = profile['current_location']['id']
          location_name = profile['current_location']['name']
          if location_id not in locations:
            locations[location_id] = dict()
            locations[location_id]['name'] = location_name
            locations[location_id]['count'] = 1
          else:
            locations[location_id]['count'] += 1
      #logging.info(locations)
      
    if user:
      userprefs = models.get_userprefs(user["id"])
    else:
      userprefs = None
    
    if userprefs:
      current_location = userprefs.location_id
      
    template = template_env.get_template('home.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,      
      'user': user,
      'userprefs': userprefs,
      'locations': locations,
      'friends_count': friends_count,
    }
    self.response.out.write(template.render(context))
    
  def post(self):
    url = self.request.get('url')
    file = urllib2.urlopen(url)
    graph = facebook.GraphAPI(self.current_user['access_token'])
    response = graph.put_photo(file, "Test Image")
    photo_url = ("http://www.facebook.com/"
                 "photo.php?fbid={0}".format(response['id']))
    self.redirect(str(photo_url))


class LogoutHandler(BaseHandler):
  def get(self):
    if self.current_user is not None:
        self.session['user'] = None

    self.redirect('/')


class PrefsPage(BaseHandler):
  def post(self):
    user = self.current_user
    logging.info("Updating preferences for user %s" % user["id"])
    userprefs = models.get_userprefs(user["id"])
    try:
      userprefs.location_id = int(self.request.get('location'))
      logging.info(userprefs.location_id)
      userprefs.put()
    except ValueError:
      # user entered value that was not integer
      pass # ignore
      
    self.redirect('/')

application = webapp2.WSGIApplication(
  [('/', MainPage), ('/logout', LogoutHandler), ('/prefs', PrefsPage)],
  config=config,
  debug=True)

