import facebook
import jinja2
import models
import os
import webapp2
from webapp2_extras import json
from datetime import datetime, timedelta
from urllib2 import HTTPError

# Store your Facebook app ID, API key, etc. in a file named secrets.py, which
# is in .gitignore to protect the innocent.
import secrets
FACEBOOK_APP_ID = secrets.FACEBOOK_APP_ID
FACEBOOK_APP_SECRET = secrets.FACEBOOK_APP_SECRET
GOOGLE_MAPS_API_KEY = secrets.GOOGLE_MAPS_API_KEY

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
  offline_token = db.StringProperty(required=False)
  offline_token_created = db.DateTimeProperty(required=False)

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
                    graph = facebook.GraphAPI(cookie["access_token"])

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
                      graph = facebook.GraphAPI(cookie["access_token"])
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
  """Return list friends for given GraphAPI client.
  Optionally filter by location ID and IS or IS NOT application user.
  Ordered by mutual friends.
  Note: When modified to not use FQL, paging support will be required.
  """
  user = graph.get_object("me")
  fql = "SELECT uid, name, profile_url, pic_big, current_location, mutual_friend_count FROM user WHERE uid IN (SELECT uid1 FROM friend WHERE uid2 = " + user["id"] + ")"
  if location_id:
    fql += " AND current_location.id=" + location_id
  if is_user:
    fql += " AND is_app_user=" + is_user
  fql += " ORDER BY mutual_friend_count DESC"
  try:
    fql_friends = graph.fql(fql)
    return fql_friends['data']
  except:
    logging.error("There was an error retrieving friends of UID %s", user["id"])
    return list()

def get_app_friends(g):
  return get_friends(g, is_user="1")

def get_non_app_friends(g):
  return get_friends(g, is_user="0")

def remove_profile_by_uid(profiles, ids):
  return [p for p in profiles if str(p['uid']) not in ids]

class MainPage(BaseHandler):
        
  def get(self):
    user = self.current_user
    locations = dict()
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
          lng = profile['current_location']['longitude']
          lat = profile['current_location']['latitude']
          if location_id not in locations:
            locations[location_id] = dict()
            locations[location_id]['name'] = location_name
            locations[location_id]['count'] = 1
            locations[location_id]['count_2'] = 0
            locations[location_id]['longitude'] = lng
            locations[location_id]['latitude'] = lat
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
        graph_friend = facebook.GraphAPI(user_friend.offline_token)

        # location of 2nd degree friends
        friends_friends = get_friends(graph_friend)

        friends_friends_not_mutual = remove_profile_by_uid(friends_friends, [user['id']])

        # save the location of the second degree friends and increment the occurrence count 
        for profile_friend in friends_friends_not_mutual:
          if not profile_friend['current_location']:
            continue
          else:
            # ignore mutual friend
            # FIXME inefficient, assumes 1st degree list is shorter than 2nd
            if any(f['uid'] == profile_friend['uid'] for f in friends):
              continue
            # ignore "me"
            if str(profile_friend['uid']) == str(user['id']):
              continue
            location_id = profile_friend['current_location']['id']
            location_name = profile_friend['current_location']['name']
            if location_id not in locations:
              locations[location_id] = dict()
              locations[location_id]['name'] = location_name
              locations[location_id]['count'] = 0
              locations[location_id]['count_2'] = 1
            else:
              locations[location_id]['count_2'] += 1
            friends_count_2 += 1

    if user:
      userprefs = models.get_userprefs(user["id"])
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
    friends_list = list()
    friends_local_not_user_uid_list = list()
    friends_with_locals_list = list()

    friends_local_user = list()
    friends_local_not_user = list()
    friends_friends_local_not_user = dict()

    if user:
      userprefs = models.get_userprefs(user['id'])
    else:
      userprefs = None
      self.redirect('/')

    if userprefs:
      graph = facebook.GraphAPI(user["access_token"])

      location_id = str(userprefs.location_id)
      location = graph.get_object(location_id)

      # get all friends
      friends = get_friends(graph)

      # get friends that are users
      friends_user = get_app_friends(graph)

      # break list into user and non-users
      friends_not_user = list()
      for friend in friends:
        if not any(p['uid'] == friend['uid'] for p in friends_user):
          friends_not_user.append(friend)

      # break into list of locals
      friends_local_user = [p for p in friends_user if p['current_location'] and str(p['current_location']['id']) == location_id]
      friends_local_not_user = [p for p in friends_not_user if p['current_location'] and str(p['current_location']['id']) == location_id]

      # 1st degree friends to invite
      for profile in friends_local_not_user:
        friends_local_not_user_uid_list.append(str(profile['uid']))

      # find 2nd degree friends at current location
      # from friends from all locations that are users
      for profile in friends_user:
        # is the friend a user?
        user_friend = User.get_by_key_name(str(profile['uid']))

        # user not in database
        # should never happen because we use friends_user
        if not user_friend:
          continue

        # query their friends using the long-lived access token
        graph_friend = facebook.GraphAPI(user_friend.offline_token)

        # 2nd degree friends at current location
        friends_friends_local_not_user2 = get_friends(graph_friend, location_id)

        # save the 2nd degree friend and add the current user as a friend
        for profile_friend in friends_friends_local_not_user2:
          # ignore mutual friend
          # FIXME inefficient, assumes 1st degree list is shorter than 2nd
          if any(f['uid'] == profile_friend['uid'] for f in friends_user):
            continue
          # ignore "me"
          if str(profile_friend['uid']) == str(user['id']):
            continue
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
        'location_name': location['name'],
        'location_link': location['link'],
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
      location_id = int(self.request.get('location'))
    except ValueError:
      # user entered value that was not integer
      pass # ignore
      self.redirect('/')

    graph = facebook.GraphAPI(user["access_token"])
    location = graph.get_object(self.request.get('location'))

    userprefs.location_id = location_id
    userprefs.location_name = location['name']
    userprefs.put()
    
    self.redirect('/friends')


class AboutPage(BaseHandler):
  def get(self):
    user = self.current_user
    if user:
      userprefs = models.get_userprefs(user['id'])
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
  [('/', MainPage), ('/logout', LogoutHandler), ('/prefs', PrefsPage), 
   ('/friends', FriendsPage),
   ('/about', AboutPage)],
  config=config,
  debug=True)

