FACEBOOK_APP_ID = "273973039422346"
FACEBOOK_APP_SECRET = "6d1d83de18c0722cd94a902180b331cb"

import datetime
import facebook
import jinja2
import models
import os
import webapp2
import urllib2

import logging
logging.getLogger().setLevel(logging.DEBUG)

from google.appengine.ext import db
from webapp2_extras import sessions

config = {}
config['webapp2_extras.sessions'] = dict(secret_key='')

template_env = jinja2.Environment(
  loader=jinja2.FileSystemLoader(os.getcwd()))


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
    current_time = datetime.datetime.now()
    user = self.current_user
    friends_list = []
    friends_limit = 10
    if user:
      graph = facebook.GraphAPI(user["access_token"])
      friends = graph.get_connections("me", "friends")
      # SELECT uid, name FROM user WHERE uid IN (SELECT uid2 FROM friend WHERE uid1 IN (SELECT uid FROM user WHERE uid IN (SELECT uid2 FROM friend WHERE uid1 = me() ) and is_app_user=1))
      #friends_ids = [int(friend['id']) for friend in friends['data']]
      #logging.info(friends_ids)
      #profiles = graph.get_objects(friends_ids)
      #logging.info(profiles)
      for friend in friends['data']:
        if 0 == friends_limit:
          logging.info("Friend limit reached")
          break
          
        #logging.info(new_friend)
        #friends_list.append(friend['name'])
        # TODO change to get_objects()
        profile = graph.get_object(friend['id'])
        logging.info(profile)
        if 'location' not in profile:
          continue
        else:
          location_name = profile['location']['name']
          friends_limit -= 1
          
        #friends_2nd = graph.get_connections(friend['id'], "friends")
        #profile_2nd = graph.get_object(friends_2nd['id'])
        #logging.info(profile_2nd)
        
        friends_list.append(Friend(
            id=str(profile['id']),
            name=profile['name'],
            link=profile['link'],
            location=location_name,
        ))
        
    if user:
      userprefs = models.get_userprefs(user["id"])
    else:
      userprefs = None
    
    if userprefs:
      current_time += datetime.timedelta(0,0,0,0,0,userprefs.tz_offset)
      
    template = template_env.get_template('home.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,      
      'current_time': current_time,
      'user': user,
      'userprefs': userprefs,
      'friends': friends_list,
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
    userprefs = models.get_userprefs(user["id"])
    try:
      tz_offset = int(self.request.get('tz_offset'))
      userprefs.tz_offset = tz_offset
      userprefs.put()
    except ValueError:
      # user entered value that was not integer
      pass # ignore
      
    self.redirect('/')


application = webapp2.WSGIApplication(
  [('/', MainPage), ('/logout', LogoutHandler), ('/prefs', PrefsPage)],
  config=config,
  debug=True)
