import datetime
import facebook
import jinja2
import models
import os
import webapp2
import urllib2

# Store your Facebook app ID, API key, etc. in a file named secrets.py, which
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
            logging.info("Check if user is logged in to Facebook.")
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
                    logging.info('New app user')
                    graph = facebook.GraphAPI(cookie["access_token"])

                    # replace with long live access token
                    token_full = graph.extend_access_token(app_id=FACEBOOK_APP_ID,app_secret=FACEBOOK_APP_SECRET)
                    token = token_full['access_token']
                    #logging.info('old token expires ' + cookie['expires'])
                    #logging.info('new token expires ' + token_full['expires'])
                    graph.access_token = token

                    # save user in objectstore
                    profile = graph.get_object("me")
                    user = User(
                        key_name=str(profile["id"]),
                        id=str(profile["id"]),
                        name=profile["name"],
                        profile_url=profile["link"],
                        access_token=token,
                    )
                    user.put()
                elif user.access_token != cookie["access_token"]:
                    logging.info('Existing app user with new access token')
                    # get long live token
                    graph = facebook.GraphAPI(cookie["access_token"])
                    token = graph.extend_access_token(app_id=FACEBOOK_APP_ID,app_secret=FACEBOOK_APP_SECRET)['access_token']
                    graph.access_token = token
                    # TODO how to update existing cookie, unless it is okay to keep extending
                    # save user in objectstore
                    user.access_token = token
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


def get_friends(graph, location_id="", is_user=""):
  """Return list friends for given GraphAPI client.
  Optionally filter by location ID and IS or IS NOT application user.
  Ordered by mutual friends.
  Note: When modified to not use FQL, paging support will be required.
  """
  user = graph.get_object("me")
  fql = "SELECT uid, name, profile_url, pic_small, current_location, mutual_friend_count FROM user WHERE uid IN (SELECT uid1 FROM friend WHERE uid2 = " + user["id"] + ")"
  if location_id:
    fql += " AND current_location.id=" + location_id
  if is_user:
    fql += " AND is_app_user=" + is_user
  fql += " ORDER BY mutual_friend_count DESC"
  logging.info(fql)
  try:
    fql_friends = graph.fql(fql)
    return fql_friends['data']
  except:
    logging.error("There was an error retrieving friends of UID %s", user["id"])
    return list()

def get_app_friends(g, l):
  return get_friends(g, l, "1")

def get_non_app_friends(g, l):
  return get_friends(g, l, "0")

class MainPage(BaseHandler):
        
  def get(self):
    user = self.current_user
    locations = dict()
    locations_2 = dict()
    friends_count = 0
    friends_count_2 = 0
    if user:
      graph = facebook.GraphAPI(user["access_token"])
      friends = get_friends(graph)
      for profile in friends:
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

      # find locations of second degree friends
      for profile in friends:
        # is the friend a user?
        user_friend = User.get_by_key_name(str(profile['uid']))

        # user not in database
        if not user_friend:
          continue

        # query their friends using the long-lived access token
        graph_friend = facebook.GraphAPI(user_friend.access_token)

        # location of 2nd degree friends
        friends_friends = get_friends(graph_friend)

        # save the location of the second degree friends and increment the occurrence count 
        for profile_friend in friends_friends:
          if not profile_friend['current_location']:
            continue
          else:
            location_id = profile_friend['current_location']['id']
            location_name = profile_friend['current_location']['name']
            if location_id not in locations_2:
              locations_2[location_id] = dict()
              locations_2[location_id]['name'] = location_name
              locations_2[location_id]['count'] = 1
            else:
              locations_2[location_id]['count'] += 1
            friends_count_2 += 1

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
      'locations_2': locations_2,
      'friends_count': friends_count,
      'friends_count_2': friends_count_2,
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

class FriendsPage(BaseHandler):

  def get(self):
    user = self.current_user
    friends_list = list()
    friends_local_not_user_uid_list = list()
    friends_with_locals_list = list()
    location_name = None

    friends_local_user = list()
    friends_local_not_user = list()
    friends_friends_local_user = dict()
    friends_friends_local_not_user = dict()

    if user:
      userprefs = models.get_userprefs(user['id'])
    else:
      userprefs = None

    if userprefs:
      graph = facebook.GraphAPI(user["access_token"])

      location_id = str(userprefs.location_id)
      location_graph = graph.fql("SELECT name FROM place WHERE page_id=" + location_id)
      location_name = location_graph['data'][0]['name']

      # 1st degree user friends at current location
      friends_local_user = get_app_friends(graph, location_id)

      # 1st degree non-user friends at current location
      friends_local_not_user = get_non_app_friends(graph, location_id)

      # 1st degree friends to invite
      for profile in friends_local_not_user:
        friends_local_not_user_uid_list.append(str(profile['uid']))

      # all friends
      friends_user = get_friends(graph)

      # find 2nd degree friends at current location
      # from friends from all locations that are users
      for profile in friends_user:

        # is the friend a user?
        user_friend = User.get_by_key_name(str(profile['uid']))

        # user not in database
        if not user_friend:
          continue

        # query their friends using the long-lived access token
        graph_friend = facebook.GraphAPI(user_friend.access_token)

        # 2nd degree friends at current location
        # TODO ignore mutual friends and "me"
        friends_friends_local_not_user2 = get_non_app_friends(graph_friend, location_id)

        # save the 2nd degree friend and add the current user as a friend
        for profile_friend in friends_friends_local_not_user2:
          if profile_friend['uid'] in friends_friends_local_not_user:
           friends_friends_local_not_user[profile_friend['uid']]['friends'].append(profile)
          else:
            profile_friend['friends'] = list()
            profile_friend['friends'].append(profile)
            friends_friends_local_not_user[profile_friend['uid']] = profile_friend

        friends_list.append(profile)

    template = template_env.get_template('friends.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,
      'user': user,
      'userprefs': userprefs,
      'friends_list': friends_list,
      'friends_local_not_user_uid_list': friends_local_not_user_uid_list,
      'friends_with_locals_list': friends_with_locals_list,
      'friends_local_user': friends_local_user,
      'friends_local_not_user': friends_local_not_user,
      'friends_friends_local_not_user': friends_friends_local_not_user,
      'location_name': location_name,
    }
    self.response.out.write(template.render(context))

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
      userprefs.put()
    except ValueError:
      # user entered value that was not integer
      pass # ignore
      self.redirect('/')

    self.redirect('/friends')


application = webapp2.WSGIApplication(
  [('/', MainPage), ('/logout', LogoutHandler), ('/prefs', PrefsPage), 
   ('/friends', FriendsPage)],
  config=config,
  debug=True)

