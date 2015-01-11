import facebook
from facebook import GraphAPIError
import jinja2
from models import User, UserPrefs, get_userprefs
import os
import webapp2
from webapp2_extras import json
from datetime import datetime, timedelta
from urllib2 import HTTPError
from ast import literal_eval as make_tuple

# Store your Facebook app ID, API key, etc. in a file named secrets.py, which
# is in .gitignore to protect the innocent.
from secrets import FACEBOOK_APP_ID, FACEBOOK_APP_SECRET, FACEBOOK_APP_NAMESPACE, GOOGLE_MAPS_API_KEY 

import logging
logging.getLogger().setLevel(logging.DEBUG)

from google.appengine.ext import db
from webapp2_extras import sessions

config = {}
config['webapp2_extras.sessions'] = dict(secret_key='')

template_env = jinja2.Environment(
  loader=jinja2.FileSystemLoader(os.path.join(os.getcwd(),'templates')))

# TODO define uniqueness so object can be hashed and used in sets
# https://stackoverflow.com/questions/4169252/remove-duplicates-in-list-of-object-with-python
class Friend():
  def __init__(self, uid, name, link, location):
    self.uid = uid
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
            logging.info("Check if user is logged in to Facebook.")
            # Either used just logged in or just saw the first page
            # We'll see here
            try:
              cookie = facebook.get_user_from_cookie(self.request.cookies,
                                                     FACEBOOK_APP_ID,
                                                     FACEBOOK_APP_SECRET)
            except HTTPError as err:
              logging.error(err.code)
              logging.error(err.reason)
              return None
              
            if cookie:
                # Okay so user logged in.
                # Now, check to see if existing user
                user = User.get_by_key_name(cookie["uid"])
                logging.info("Cookie found, user is logged in.")
                if not user:
                    logging.info('New app user')
                    graph = facebook.GraphAPI(version=2.1,access_token=cookie["access_token"])

                    # also get long live access token for approved off-line access
                    offline_token_full = graph.extend_access_token(app_id=FACEBOOK_APP_ID,app_secret=FACEBOOK_APP_SECRET)
                    offline_token = offline_token_full["access_token"]
                    #logging.info('old token expires %s', cookie['expires'])
                    #logging.info('new token expires %s', offline_token_full['expires'])

                    profile = graph.get_object("me")
                    user = User(
                        key_name=str(profile["id"]),
                        id=str(profile["id"]),
                        name=profile["name"],
                        profile_url=profile["link"],
                        access_token=cookie["access_token"],
                        offline_token=offline_token,
                        offline_token_created=datetime.utcnow(),
                    )
                    user.put()
                elif user.access_token != cookie["access_token"]:
                    logging.info('Existing app user with new access token')

                    # Facebook will only extend the expiration time once per day
                    # @see https://developers.facebook.com/docs/roadmap/completed-changes/offline-access-removal
                    if user.offline_token_created.date() < datetime.utcnow().date(): 
                      graph = facebook.GraphAPI(version=2.1,access_token=cookie["access_token"])
                      user.offline_token = graph.extend_access_token(app_id=FACEBOOK_APP_ID,app_secret=FACEBOOK_APP_SECRET)['access_token']
                      user.offline_token_created = datetime.utcnow()

                    user.access_token = cookie["access_token"]
                    user.put()

                access_token_expires = (datetime.utcnow() + timedelta(0,int(cookie["expires"])))
                # User is now logged in
                self.session["user"] = dict(
                    name=user.name,
                    profile_url=user.profile_url,
                    id=user.id,
                    access_token=user.offline_token,
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

def chunks(l, n):
  """ Yield successive n-sized chunks from l.
      From Ned Batchelder (http://stackoverflow.com/a/312464/388127)
  """
  for i in xrange(0, len(l), n):
      yield l[i:i+n]

def get_friends(graph, location_id="", is_user=""):
  """Return list app user friends for given GraphAPI client.
  TODO Optionally filter by location ID and IS or IS NOT application user.
  TODO Order by mutual friends. DEPRECATED in Graph API 2.x+
  TODO paging support required.
  """
  user = graph.get_object("me")
  #friends = graph.get_connections(user["id"],"friends")
  # could not add fields to get_connections, e.g. "fields=friends{id,link,name,location}"
  try:
    friends = graph.get_object(user["id"]+"/friends",fields="id,name,link,location,picture")
    return friends['data']
  except GraphAPIError as ge:
    logging.error("Error retrieving friends of UID %s: %s", user["id"], ge)
    return list()
  except Exception as e:
    logging.error("Error retrieving friends of UID %s: %s", user["id"], e)
    return list()
  
def get_app_friends(g):
  return get_friends(g, is_user="1")

def get_non_app_friends(g):
  return get_friends(g, is_user="0")

def remove_profile_by_id(profiles, ids):
  return [p for p in profiles if str(p['id']) not in ids]

def is_app_user(uid):
  if User.get_by_key_name(uid) and UserPrefs.get_by_key_name(uid):
    return True
  else:
    return False

def is_local(uid,latlng):
  userprefs = UserPrefs.get_by_key_name(uid)
  if not userprefs:
    return False
  return userprefs.location_lat == latlng[0] and userprefs.location_lng == latlng[1]

class MainPage(BaseHandler):
        
  def get(self):
    user = self.current_user
    locations = dict()
    friends_count = 0
    friends_count_2 = 0
    if user:
      graph = facebook.GraphAPI(version=2.1,access_token=user["access_token"])

      friends = get_friends(graph)
      friends[:] = [friend for friend in friends if is_app_user(str(friend['id']))]
      for profile in friends:
        friends_count += 1
        friend_prefs = UserPrefs.get_by_key_name(str(profile['id']))
        location_name = friend_prefs.location_name
        location_lng = friend_prefs.location_lng
        location_lat = friend_prefs.location_lat
        location_id = (location_lat,location_lng)
        if location_id not in locations:
          locations[location_id] = dict()
          locations[location_id]['name'] = location_name
          locations[location_id]['count'] = 1
          locations[location_id]['count_2'] = 0
          locations[location_id]['longitude'] = location_lng
          locations[location_id]['latitude'] = location_lat
        else:
          locations[location_id]['count'] += 1
        
        friend_user = User.get_by_key_name(str(profile['id']))
        graph_friend = facebook.GraphAPI(version=2.1,access_token=friend_user.offline_token)

        friends_2 = get_friends(graph_friend)
        friends_2[:] = [friend for friend in friends_2 if is_app_user(str(friend['id']))]
        friends_1_2_with_out_mutual = remove_profile_by_id(friends_2, [user['id']])
 
        for profile_2 in friends_1_2_with_out_mutual:
          # ignore mutual friend
          # FIXME inefficient, assumes 1st degree list is shorter than 2nd
          if any(f['id'] == profile_2['id'] for f in friends):
            continue
          # ignore "me"
          if str(profile_2['id']) == str(user['id']):
            continue
          friends_count_2 += 1
          friend_prefs_2 = UserPrefs.get_by_key_name(str(profile_2['id']))
          location_name = friend_prefs_2.location_name
          location_lng = friend_prefs_2.location_lng
          location_lat = friend_prefs_2.location_lat
          location_id = (location_lat,location_lng)
          if location_id not in locations:
            locations[location_id] = dict()
            locations[location_id]['name'] = location_name
            locations[location_id]['count'] = 0
            locations[location_id]['count_2'] = 1
            locations[location_id]['longitude'] = location_lng
            locations[location_id]['latitude'] = location_lat
          else:
            locations[location_id]['count_2'] += 1

    if user:
      userprefs = get_userprefs(user["id"])
    else:
      userprefs = None
    
    locations_list = sorted(locations.items(), key=lambda l: l[1]['name'])

    template = template_env.get_template('home.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,
      'user': user,
      'userprefs': userprefs,
      'locations': locations_list,
      'friends_count': friends_count,
      'friends_count_2': friends_count_2,
      'google_maps_api_key': GOOGLE_MAPS_API_KEY,
      'markers': json.encode(locations_list),
    }
    self.response.out.write(template.render(context))


class FriendsPage(BaseHandler):

  def get(self):
    user = self.current_user
    if not user:
      self.redirect('/')
    userprefs = get_userprefs(user['id'])
    if not userprefs:
      self.redirect('/')
    
    search_latlng = (userprefs.search_lat,userprefs.search_lng)

    friends_local_not_user_uid_list = list()
    friends_with_locals_list = list()
    friends_local_2 = dict()
    
    graph = facebook.GraphAPI(version=2.1,access_token=user["access_token"])

    friends = get_friends(graph)
    friends[:] = [friend for friend in friends if is_app_user(str(friend['id']))]
    friends_local = [friend for friend in friends if is_local(str(friend['id']),search_latlng)]
    
    for profile in friends:
      user_friend = User.get_by_key_name(str(profile['id']))

      graph_friend = facebook.GraphAPI(version=2.1,access_token=user_friend.offline_token)

      friends_2 = get_friends(graph_friend)
      friends_2[:] = [friend for friend in friends_2 if is_app_user(str(friend['id']))]
      friends_2_local = [friend for friend in friends_2 if is_local(str(friend['id']),search_latlng)]
    
      for profile_2 in friends_2_local:
        # ignore mutual friend
        # FIXME inefficient, assumes 1st degree list is shorter than 2nd, use sets?
        if any(f['id'] == profile_2['id'] for f in friends):
          continue
        # ignore "me"
        if str(profile_2['id']) == str(user['id']):
          continue
        if profile_2['id'] in friends_local_2:
          friends_local_2[profile_2['id']]['friends'].append(profile)
        else:
          profile_2['friends'] = list()
          profile_2['friends'].append(profile)
          friends_local_2[profile_2['id']] = profile_2

    template = template_env.get_template('friends.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,
      'facebook_app_namespace': FACEBOOK_APP_NAMESPACE,
      'user': user,
      'userprefs': userprefs,
      'location_name': search_latlng,
      'location_link': "https://www.meetdazy.com/",
      'friends_local': friends_local,
      'friends_local_2': friends_local_2,
      'friends_local_not_user_uid_list': friends_local_not_user_uid_list,
      'friends_with_locals_list': friends_with_locals_list,
    }
    self.response.out.write(template.render(context))

class LogoutHandler(BaseHandler):
  def get(self):
    if self.current_user is not None:
        self.session['user'] = None

    self.redirect('/')

class ProfilePage(BaseHandler):
  def get(self):
    user = self.current_user

    if user:
      userprefs = get_userprefs(user["id"])
    else:
      userprefs = None

    template = template_env.get_template('profile.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,
      'user': user,
      'userprefs': userprefs,
      #'google_maps_api_key': GOOGLE_MAPS_API_KEY,
    }
    self.response.out.write(template.render(context))    
  
  def post(self):
    user = self.current_user
    logging.info("Updating profile for user %s" % user["id"])
    userprefs = get_userprefs(user["id"])
    try:
      lat = float(self.request.get('latitude'))
      lng = float(self.request.get('longitude'))
    except ValueError:
      # user entered value that was not integer
      pass # ignore
      self.redirect('/')
    location_name = self.request.get('location')
    userprefs.location_lat = lat
    userprefs.location_lng = lng
    userprefs.location_name = location_name
    userprefs.put()
    self.redirect('/')
  
class PrefsPage(BaseHandler):
  def post(self):
    user = self.current_user
    try:
      search_latlng = make_tuple(self.request.get('location_latlng'))
    except ValueError:
      self.redirect('/')
    logging.info("Updating preferences for user %s" % user["id"])
    userprefs = get_userprefs(user["id"])
    userprefs.search_name = self.request.get('location_name')
    userprefs.search_lat = float(search_latlng[0])
    userprefs.search_lng = float(search_latlng[1])
    userprefs.put()
    self.redirect('/friends')


class AboutPage(BaseHandler):
  def get(self):
    user = self.current_user
    if user:
      userprefs = get_userprefs(user['id'])
    else:
      userprefs = None
    template = template_env.get_template('about.html')
    context = {
      'facebook_app_id': FACEBOOK_APP_ID,
      'user': user,
      'userprefs': userprefs,
    }
    self.response.out.write(template.render(context))

application = webapp2.WSGIApplication(
  [('/', MainPage), 
   ('/logout', LogoutHandler), 
   ('/prefs', PrefsPage), 
   ('/friends', FriendsPage),
   ('/profile', ProfilePage),
   ('/about', AboutPage)],
  config=config,
  debug=True)

