# -*- coding: utf-8 -*-

# Copyright (c) 2014, KOL
# Copyright (c) 2019, Tim Angus
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <organization> nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from urllib import urlencode
from time import time
from updater import Updater
from datetime import datetime, timedelta
from threading import Thread, Lock

Video = SharedCodeService.video

PREFIX = '/video/youtubetv'

ART = 'art-default.jpg'
ICON = 'icon-default.png'
TITLE = u'%s' % L('Title')

YT_CLIENT_ID = (
    '383749313750-e0fj400djq4lukahnfjfqg6ckdbets63'
    '.apps.googleusercontent.com'
)
YT_SECRET = 'rHHvL6tgl8Ej9KngduayT2ce'
YT_SCOPE = 'https://www.googleapis.com/auth/youtube'
YT_VERSION = 'v3'

ICONS = {
    'likes': R('heart-full.png'),
    'favorites': R('star-2.png'),
    'uploads': R('outbox-2.png'),
    'watchHistory': R('revert.png'),
    'watchLater': R('clock.png'),
    'subscriptions': R('podcast-2.png'),
    'browseChannels': R('grid-2.png'),
    'playlists': R('list.png'),
    'whatToWhatch': R('home.png'),
    'account': R('user-2.png'),
    'categories': R('store.png'),
    'options': R('settings.png'),
    'suggestions': R('tag.png'),
    'remove': R('bin.png'),
    'next': R('arrow-right.png'),
    'offline': R('power.png'),
    'search': R('search.png'),
}

YT_EDITABLE = {
    'likes': L('I like this'),
    'favorites': L('Add to favorites'),
}

YT_MIN_REFRESH_INTERVAL_SECONDS = 300

###############################################################################
# Init
###############################################################################

Plugin.AddViewGroup(
    'details',
    viewMode='InfoList',
    type=ViewType.List,
    summary=SummaryTextType.Long
)


def Start():
    HTTP.CacheTime = CACHE_1HOUR
    ValidatePrefs()


def ValidatePrefs():
    loc = GetLanguage()
    if Core.storage.file_exists(Core.storage.abs_path(
        Core.storage.join_path(
            Core.bundle_path,
            'Contents',
            'Strings',
            '%s.json' % loc
        )
    )):
        Locale.DefaultLocale = loc
    else:
        Locale.DefaultLocale = 'en-us'


###############################################################################
# Video
###############################################################################

@handler(PREFIX, TITLE, thumb=ICON)
def MainMenu(complete=False, offline=False):
    oc = ObjectContainer(title2=TITLE, no_cache=True, replace_parent=False)
    if offline:
        ResetToken()

    if not CheckToken():
        oc.add(DirectoryObject(
            key=Callback(Authorization),
            title=u'%s' % L('Authorize'),
            thumb=ICONS['options'],
        ))
        if complete:
            oc.header = L('Authorize')
            oc.message = L('You must enter code for continue')
        return oc

    Updater(PREFIX+'/update', oc)

    oc.add(DirectoryObject(
        key=Callback(SubscriptionFeed, title=L('Subscription Feed')),
        title=u'%s' % L('My Subscription Feed'),
        thumb=ICONS['subscriptions'],
    ))
    oc.add(DirectoryObject(
        key=Callback(Category, title=L('What to Watch')),
        title=u'%s' % L('What to Watch'),
        thumb=ICONS['whatToWhatch'],
    ))
    oc.add(DirectoryObject(
        key=Callback(Playlists, uid='me', title=L('Playlists')),
        title=u'%s' % L('Playlists'),
        thumb=ICONS['playlists'],
    ))
    oc.add(DirectoryObject(
        key=Callback(Categories, title=L('Categories'), c_type='video'),
        title=u'%s' % L('Categories'),
        thumb=ICONS['categories'],
    ))
    oc.add(DirectoryObject(
        key=Callback(Categories, title=L('Browse channels'), c_type='guide'),
        title=u'%s' % L('Browse channels'),
        thumb=ICONS['browseChannels'],
    ))
    oc.add(DirectoryObject(
        key=Callback(Channel, oid='me', title=L('My channel')),
        title=u'%s' % L('My channel'),
        thumb=ICONS['account'],
    ))
    oc.add(InputDirectoryObject(
        key=Callback(
            Search,
            s_type='video',
            title=u'%s' % L('Search Video')
        ),
        title=u'%s' % L('Search'), prompt=u'%s' % L('Search Video'),
        thumb=ICONS['search']
    ))

    # Do a feed update when the main menu is shown, since it'll
    # usually be what the user is going to do anyway
    UpdateSubscriptionFeed()

    return AddSubscriptions(oc, uid='me')

subscription_feed_thread = None
# Guard against concurrent accesses to Data store; you'd hope this is
# already thread safe, but locking it can't hurt
subscription_feed_mutex = Lock()

# Strictly speaking this should probably be locked, but it's
# unlikely to actually matter in the real world
subscription_feed_update_progress = 0

def UpdateSubscriptionFeedWorker(duration = timedelta(weeks = 1)):
    global subscription_feed_mutex
    global subscription_feed_update_progress

    if not CheckToken():
        return

    channelIds = []
    offset = None

    while True:
        res = ApiRequest('subscriptions', ApiGetParams(
            uid='me',
            limit='50', # Max allowed by API
            offset=offset
        ))

        if not res:
            break

        if 'items' not in res:
            break

        offset = None

        for item in res['items']:
            item = item['snippet']
            channelId = item['resourceId']['channelId']
            channelIds.append(channelId)

        if 'nextPageToken' in res:
            offset = res['nextPageToken']

        if offset is None:
            break

    now = datetime.utcnow()
    now = now.replace(hour = 0, minute = 0, second = 0, microsecond = 0)
    cutoff = now - duration
    rfc3339Cutoff = cutoff.isoformat('T') + 'Z'

    videos = []
    channelsUpdated = 0
    # FIXME: this could potentially be sped up by threading the requests,
    # or some kind of async http shenanigans
    # You could also potentially avoid re-requesting videos that have
    # been saved in the Data store, but that's only really going to help
    # if the subscribed channels publish more than 50 videos per the
    # requested duration, and that seems pretty unlikely
    for channelId in channelIds:
        offset = None

        while True:
            res = ApiRequest('search', ApiGetParams(
                channelId=channelId,
                type='video',
                order='date',
                limit='50', # Max allowed by API
                publishedAfter=rfc3339Cutoff,
                offset=offset
            ))

            if not res:
                break

            if 'items' not in res:
                break

            offset = None

            for item in res['items']:
                videoId = item['id']['videoId']
                date = item['snippet']['publishedAt']
                videos.append((videoId, date))

            if 'nextPageToken' in res:
                offset = res['nextPageToken']

            if offset is None:
                break

        channelsUpdated = channelsUpdated + 1
        subscription_feed_update_progress = int((channelsUpdated * 100) / len(channelIds))

    videos.sort(reverse = True, key = lambda tup: tup[1])
    videoIds = [tup[0] for tup in videos]

    subscription_feed_mutex.acquire()
    try:
        Data.SaveObject('subscription_feed', videoIds)
    finally:
        subscription_feed_mutex.release()

def UpdateSubscriptionFeed():
    global subscription_feed_thread

    if subscription_feed_thread is not None and not subscription_feed_thread.isAlive():
        # There was a previous update, but it has finished
        subscription_feed_thread = None

    timeSinceRefreshStarted = 0
    lastRefreshTime = 0
    now = int(time())

    if 'last_refresh_time' in Dict:
        lastRefreshTime = Dict['last_refresh_time']

    if lastRefreshTime < now:
        timeSinceRefreshStarted = now - lastRefreshTime

    if subscription_feed_thread is None and \
            (timeSinceRefreshStarted > YT_MIN_REFRESH_INTERVAL_SECONDS or \
            not Data.Exists('subscription_feed')):
        # Start an update
        subscription_feed_thread = Thread(target=UpdateSubscriptionFeedWorker)
        subscription_feed_thread.start()
        lastRefreshTime = now
        Dict['last_refresh_time'] = lastRefreshTime

@route(PREFIX + '/subscriptionfeed')
def SubscriptionFeed(title, offset=0, refresh=0):
    global subscription_feed_thread
    global subscription_feed_mutex
    global subscription_feed_update_progress

    refresh=bool(int(refresh))
    oc = ObjectContainer(title2=u'%s' % title,
        # These members don't appear to actually work, but maybe some clients support them
        no_history=refresh, replace_parent=refresh)

    UpdateSubscriptionFeed()

    if subscription_feed_thread is not None and subscription_feed_thread.isAlive():
        # Give the update a little time to complete, in case it returns very
        # quickly due to caching
        subscription_feed_thread.join(2.0)

        # If the thread is still alive, it means an update is in progress...
        if subscription_feed_thread is not None and subscription_feed_thread.isAlive():
            # ...and we should let the user know about it
            oc.add(DirectoryObject(
                key=Callback(SubscriptionFeed,
                    title=L('Subscription Feed'),
                    refresh=int(refresh) + 1),
                title=u'%s%d%s' % (L('Updating ('),
                    subscription_feed_update_progress,
                    L('%)')),
                thumb=ICONS['watchHistory']
            ))

    videoIds = []
    subscription_feed_mutex.acquire()
    try:
        if Data.Exists('subscription_feed'):
            videoIds = Data.LoadObject('subscription_feed')
    finally:
        subscription_feed_mutex.release()

    if videoIds:
        offset = int(offset)
        perPage = int(Prefs['items_per_page'])
        pagelimit = offset + perPage
        pagelimit = min(pagelimit, len(videoIds))

        [AddVideos(
            oc,
            ApiGetVideos(ids=videoIds[i:i + perPage]),
            extended=Prefs['my_subscriptions_extened']
        ) for i in xrange(offset, pagelimit, perPage)]

        if pagelimit < len(videoIds):
            oc.add(NextPageObject(
                key = Callback(
                    SubscriptionFeed,
                    title=title,
                    offset=pagelimit
                ),
                title = u'%s' % L('Next page'),
                thumb = ICONS['next']
            ))

    return oc


@route(PREFIX + '/video/view')
def VideoView(vid, **kwargs):
    return URLService.MetadataObjectForURL(
        url=Video.GetServiceURL(vid, Dict['access_token'], GetLanguage()),
        in_container=True
    )


@route(PREFIX + '/video/info')
def VideoInfo(vid, pl_item_id=None):
    oc = ObjectContainer()
    res = ApiGetVideos(ids=[vid])

    AddVideos(oc, res, title=L('Play video'))

    if not len(oc):
        return NoContents()

    item = res['items'][0]

    oc.title2 = u'%s' % item['snippet']['localized']['title']

    oc.add(DirectoryObject(
        key=Callback(
            Channel,
            oid=item['snippet']['channelId'],
            title=item['snippet']['channelTitle']
        ),
        title=u'%s' % item['snippet']['channelTitle'],
        thumb=ICONS['account'],
    ))

    oc.add(DirectoryObject(
        key=Callback(
            Search,
            title=L('Related videos'),
            query=None,
            relatedToVideoId=item['id']
        ),
        title=u'%s' % L('Related videos'),
        thumb=ICONS['suggestions'],
    ))

    for key, title in YT_EDITABLE.items():
        oc.add(DirectoryObject(
            key=Callback(PlaylistAdd, aid=item['id'], key=key),
            title=u'%s' % title,
            thumb=ICONS[key],
        ))

    if pl_item_id:
        oc.add(DirectoryObject(
            key=Callback(PlaylistRemove, pl_item_id=pl_item_id),
            title=u'%s' % L('Remove from playlist'),
            thumb=ICONS['remove'],
        ))

    return AddItemsFromDescription(
        oc,
        item['snippet']['localized']['description']
    )


@route(PREFIX + '/channels')
def Channels(oid, title, offset=None):
    res = ApiRequest('channels', ApiGetParams(
        categoryId=oid,
        hl=GetLanguage(),
        limit=Prefs['items_per_page'],
        offset=offset
    ))

    if not res or not len(res['items']):
        return NoContents()

    oc = ObjectContainer(
        title2=u'%s' % title,
        replace_parent=bool(offset)
    )

    for item in res['items']:
        cid = item['id']
        item = item['snippet']

        oc.add(DirectoryObject(
            key=Callback(
                Channel,
                oid=cid,
                title=item['title']
            ),
            title=u'%s' % item['title'],
            summary=u'%s' % item['description'],
            thumb=GetThumbFromSnippet(item),
        ))

    if 'nextPageToken' in res:
        oc.add(NextPageObject(
            key=Callback(
                Channels,
                oid=oid,
                title=title,
                offset=res['nextPageToken'],
            ),
            title=u'%s' % L('Next page'),
            thumb=ICONS['next']
        ))

    return oc


@route(PREFIX + '/channel')
def Channel(oid, title):
    oc = ObjectContainer(
        title2=u'%s' % title
    )

    # Add standard menu
    FillChannelInfo(oc, oid)
    if oid == 'me':
        oc.add(DirectoryObject(
            key=Callback(MainMenu, offline=True),
            title=u'%s' % L('Sign out'),
            thumb=ICONS['offline'],
        ))
        return oc

    oc.add(DirectoryObject(
        key=Callback(
            Subscriptions,
            title=u'%s - %s' % (title, L('Subscriptions')),
            uid=oid
        ),
        title=u'%s' % L('Subscriptions'),
        thumb=ICONS['subscriptions'],
    ))
    oc.add(InputDirectoryObject(
        key=Callback(
            Search,
            s_type='video',
            channelId=oid,
            title=u'%s' % L('Search Channel')
        ),
        title=u'%s' % L('Search'), prompt=u'%s' % L('Search Channel'),
        thumb=ICONS['search']
    ))
    AddPlaylists(oc, uid=oid)

    return oc


@route(PREFIX + '/user')
def User(username):
    res = ApiRequest('channels', ApiGetParams(
        forUsername=username,
        hl=GetLanguage()
    ))

    if not res or not len(res['items']):
        return NoContents()

    item = res['items'][0]

    return Channel(item['id'], item['snippet']['localized']['title'])


@route(PREFIX + '/categories')
def Categories(title, c_type):
    res = ApiRequest('%sCategories' % c_type, ApiGetParams(
        regionCode=GetRegion(),
        hl=GetLanguage()
    ))

    if not res or not len(res['items']):
        return NoContents()

    oc = ObjectContainer(
        title2=u'%s' % title
    )

    if c_type == 'guide':
        c_callback = Channels
        oc.add(InputDirectoryObject(
            key=Callback(
                Search,
                s_type='channel',
                title=u'%s' % L('Search channels')
            ),
            title=u'%s' % L('Search'), prompt=u'%s' % L('Search channels'),
            thumb=ICONS['search']
        ))
    else:
        c_callback = Category

    for item in res['items']:
        oc.add(DirectoryObject(
            key=Callback(
                c_callback,
                title=item['snippet']['title'],
                oid=item['id']
            ),
            title=u'%s' % item['snippet']['title']
        ))

    return oc


@route(PREFIX + '/category')
def Category(title, oid=0, offset=None):
    oc = ObjectContainer(
        title2=u'%s' % title,
        replace_parent=bool(offset)
    )
    res = ApiGetVideos(
        chart='mostPopular',
        limit=Prefs['items_per_page'],
        offset=offset,
        regionCode=GetRegion(),
        videoCategoryId=oid
    )
    AddVideos(oc, res, extended=Prefs['category_extened'])

    if not len(oc):
        return NoContents()

    if 'nextPageToken' in res:
        oc.add(NextPageObject(
            key=Callback(
                Category,
                title=oc.title2,
                oid=oid,
                offset=res['nextPageToken'],
            ),
            title=u'%s' % L('Next page'),
            thumb=ICONS['next']
        ))

    return oc


@route(PREFIX + '/playlists')
def Playlists(uid, title, offset=None):
    oc = ObjectContainer(
        title2=u'%s' % title,
        replace_parent=bool(offset)
    )

    if not offset and uid == 'me':
        FillChannelInfo(oc, uid)
        oc.add(InputDirectoryObject(
            key=Callback(
                Search,
                s_type='playlist',
                title=u'%s' % L('Search playlists')
            ),
            title=u'%s' % L('Search'), prompt=u'%s' % L('Search playlists'),
            thumb=ICONS['search']
        ))

    return AddPlaylists(oc, uid=uid, offset=offset)


@route(PREFIX + '/playlist')
def Playlist(oid, title, can_edit=False, offset=None):

    res = ApiRequest('playlistItems', ApiGetParams(
        part='contentDetails',
        playlistId=oid,
        offset=offset,
        limit=Prefs['items_per_page']
    ))

    if not res or not len(res['items']):
        return NoContents()

    oc = ObjectContainer(
        title2=u'%s' % title,
        replace_parent=bool(offset)
    )

    ids = []
    pl_map = {}
    can_edit = can_edit and can_edit != 'False'

    for item in res['items']:
        ids.append(item['contentDetails']['videoId'])
        if can_edit:
            pl_map[item['contentDetails']['videoId']] = item['id']

    AddVideos(
        oc,
        ApiGetVideos(ids=ids),
        extended=Prefs['playlists_extened'],
        pl_map=pl_map
    )

    if 'nextPageToken' in res:
        oc.add(NextPageObject(
            key=Callback(
                Playlist,
                title=oc.title2,
                oid=oid,
                can_edit=can_edit,
                offset=res['nextPageToken'],
            ),
            title=u'%s' % L('Next page'),
            thumb=ICONS['next']
        ))

    return oc


@route(PREFIX + '/playlist/add')
def PlaylistAdd(aid, key=None, oid=None, a_type='video'):
    if key is not None:
        items = ApiGetChannelInfo('me')['playlists']
        if key in items:
            oid = items[key]

    if not oid:
        return ErrorMessage()

    res = ApiRequest('playlistItems', {'part': 'snippet'}, data={
        'snippet': {
            'playlistId': oid,
            'resourceId': {
                'kind': 'youtube#'+a_type,
                a_type+'Id': aid,
            }
        }
    })

    if not res:
        return ErrorMessage()

    return SuccessMessage()


def PlaylistRemove(pl_item_id):
    if ApiRequest('playlistItems', {'id': pl_item_id}, rmethod='DELETE'):
        return SuccessMessage()

    return ErrorMessage()


@route(PREFIX + '/subscriptions')
def Subscriptions(uid, title, offset=None):
    oc = ObjectContainer(
        title2=u'%s' % L('Subscriptions'),
        replace_parent=bool(offset)
    )
    return AddSubscriptions(oc, uid=uid, offset=offset)


def AddVideos(oc, res, title=None, extended=False, pl_map={}):
    if not res or not len(res['items']):
        return oc

    for item in res['items']:
        snippet = item['snippet']

        # Skip upcoming videos; we only want things we can actually watch
        if 'liveBroadcastContent' in snippet and snippet['liveBroadcastContent'] == 'upcoming':
            continue

        seconds = Video.ParseDuration(item['contentDetails']['duration'])
        milliseconds = seconds * 1000

        if Prefs['duration_in_description']:
            durationString = u'[%s] ' % SecondsToString(seconds)
        else:
            durationString = ''

        summary = u'%s%s\n%s' % (durationString, snippet['channelTitle'], snippet['description'])

        if extended:
            pl_item_id = pl_map[item['id']] if item['id'] in pl_map else None
            oc.add(DirectoryObject(
                key=Callback(VideoInfo, vid=item['id'], pl_item_id=pl_item_id),
                title=u'%s' % snippet['title'],
                summary=summary,
                thumb=GetThumbFromSnippet(snippet),
                duration=milliseconds,
            ))
        else:
            oc.add(VideoClipObject(
                key=Callback(VideoView, vid=item['id']),
                rating_key=Video.GetServiceURL(item['id']),
                title=u'%s' % snippet['title'] if title is None else title,
                summary=summary,
                thumb=GetThumbFromSnippet(snippet),
                duration=milliseconds,
                originally_available_at=Datetime.ParseDate(
                    snippet['publishedAt']
                ).date(),
                items=URLService.MediaObjectsForURL(
                    Video.GetServiceURL(item['id'], Dict['access_token'])
                )
            ))

    return oc


def FillChannelInfo(oc, uid):
    info = ApiGetChannelInfo(uid)

    if info['banner'] is not None:
        oc.art = info['banner']

    if not info['playlists']:
        return oc

    items = info['playlists']

    for key in sorted(items):
        oc.add(DirectoryObject(
            key=Callback(
                Playlist,
                oid=items[key],
                title=L(key),
                can_edit=uid == 'me' and key in YT_EDITABLE
            ),
            title=u'%s' % L(key),
            thumb=ICONS[key] if key in ICONS else None,
        ))

    return oc


def AddPlaylists(oc, uid, offset=None):
    res = ApiRequest('playlists', ApiGetParams(
        uid=uid,
        limit=GetLimitForOC(oc),
        offset=offset,
        hl=GetLanguage()
    ))

    if res:
        if 'items' in res:
            for item in res['items']:
                oid = item['id']
                item = item['snippet']

                oc.add(DirectoryObject(
                    key=Callback(
                        Playlist,
                        oid=oid,
                        title=item['localized']['title'],
                        can_edit=uid == 'me'
                    ),
                    title=u'%s' % item['localized']['title'],
                    summary=u'%s' % item['localized']['description'],
                    thumb=GetThumbFromSnippet(item),
                ))

        if 'nextPageToken' in res:
            oc.add(NextPageObject(
                key=Callback(
                    Playlists,
                    uid=uid,
                    title=oc.title2,
                    offset=res['nextPageToken'],
                ),
                title=u'%s' % L('More playlists'),
                thumb=ICONS['next']
            ))

    if not len(oc):
        return NoContents()

    return oc


def AddSubscriptions(oc, uid, offset=None):
    res = ApiRequest('subscriptions', ApiGetParams(
        uid=uid,
        limit=GetLimitForOC(oc),
        offset=offset,
        order=str(Prefs['subscriptions_order']).lower()
    ))

    if res:
        if 'items' in res:
            for item in res['items']:
                item = item['snippet']
                oc.add(DirectoryObject(
                    key=Callback(
                        Channel,
                        oid=item['resourceId']['channelId'],
                        title=item['title']
                    ),
                    title=u'%s' % item['title'],
                    summary=u'%s' % item['description'],
                    thumb=GetThumbFromSnippet(item),
                ))

        if 'nextPageToken' in res:
            offset = res['nextPageToken']
            oc.add(NextPageObject(
                key=Callback(
                    Subscriptions,
                    uid=uid,
                    title=oc.title2,
                    offset=offset,
                ),
                title=u'%s' % L('More subscriptions'),
                thumb=ICONS['next']
            ))

    if not len(oc):
        return NoContents()

    return oc


def AddItemsFromDescription(oc, description):
    links = Video.ParseLinksFromDescription(description)

    if not len(links):
        return oc;

    for (ext_title, url) in links:
        ext_title = ext_title.strip()

        if '/user/' in url:
            oc.add(DirectoryObject(
                key=Callback(User, username=Video.GetOID(url)),
                title=u'[*] %s' % ext_title,
            ))
            continue
        elif '/channel/' in url:
            oc.add(DirectoryObject(
                key=Callback(Channel, oid=Video.GetOID(url), title=ext_title),
                title=u'[*] %s' % ext_title,
            ))
            continue

        try:
            ext_vid = URLService.NormalizeURL(url)
        except:
            continue

        if ext_vid is None:
            continue

        if 'playlist?' in ext_vid:
            ext_vid = ext_vid[ext_vid.rfind('list=')+5:]
            oc.add(DirectoryObject(
                key=Callback(Playlist, oid=ext_vid, title=ext_title),
                title=u'[*] %s' % ext_title
            ))
        else:
            ext_vid = Video.GetOID(ext_vid)
            oc.add(DirectoryObject(
                key=Callback(VideoInfo, vid=ext_vid),
                title=u'[*] %s' % ext_title,
                thumb=Video.GetThumb(ext_vid)
            ))

    return oc


def Search(query=None, title=L('Search'), s_type='video', offset=0, **kwargs):
    if not query and not kwargs:
        return NoContents()

    is_video = s_type == 'video'
    res = ApiRequest('search', ApiGetParams(
        part='id' if is_video else 'snippet',
        q=query,
        type=s_type,
        regionCode=GetRegion(),
        videoDefinition='high' if is_video and Prefs['search_hd'] else '',
        offset=offset,
        limit=Prefs['items_per_page'],
        **kwargs
    ))

    if not res or not len(res['items']):
        return NoContents()

    oc = ObjectContainer(
        title2=u'%s' % title,
        replace_parent=bool(offset)
    )

    if is_video:
        ids = []
        for item in res['items']:
            ids.append(item['id']['videoId'])

        AddVideos(oc, ApiGetVideos(ids=ids), extended=Prefs['search_extened'])
    else:
        s_callback = Channel if s_type == 'channel' else Playlist
        s_key = s_type+'Id'

        for item in res['items']:
            oid = item['id'][s_key]
            item = item['snippet']
            oc.add(DirectoryObject(
                key=Callback(
                    s_callback,
                    title=item['title'],
                    oid=oid
                ),
                title=u'%s' % item['title'],
                summary=u'%s' % item['description'],
                thumb=GetThumbFromSnippet(item),
            ))

    if 'nextPageToken' in res:
        oc.add(NextPageObject(
            key=Callback(
                Search,
                query=query,
                title=oc.title2,
                s_type=s_type,
                offset=res['nextPageToken'],
                **kwargs
            ),
            title=u'%s' % L('Next page'),
            thumb=ICONS['next']
        ))

    return oc


@route(PREFIX + '/authorization')
def Authorization():
    code = None
    if CheckAccessData('device_code'):
        code = Dict['user_code']
        url = Dict['verification_url']
    else:
        res = OAuthRequest({'scope': YT_SCOPE}, 'device/code')
        if res:
            code = res['user_code']
            url = res['verification_url']
            StoreAccessData(res)

    if code:
        oc = ObjectContainer(
            view_group='details',
            no_cache=True,
            objects=[
                DirectoryObject(
                    key=Callback(MainMenu, complete=True),
                    title=u'%s' % F('codeIs', code),
                    summary=u'%s' % F('enterCodeSite', code, url),
                    tagline=url,
                ),
                DirectoryObject(
                    key=Callback(MainMenu, complete=True),
                    title=u'%s' % L('Authorize'),
                    summary=u'%s' % L('Complete authorization'),
                ),
            ]
        )
        return oc

    return ObjectContainer(
        header=u'%s' % L('Error'),
        message=u'%s' % L('Service temporarily unavailable')
    )


###############################################################################
# Common
###############################################################################

def SecondsToString(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return u'%d:%02d:%02d' % (hours, minutes, seconds)

    return u'%d:%02d' % (minutes, seconds)

def NoContents():
    return ObjectContainer(
        header=u'%s' % L('Error'),
        message=u'%s' % L('No entries found')
    )


def SuccessMessage():
    return ObjectContainer(
        header=u'%s' % L('Success'),
        message=u'%s' % L('Action complete')
    )


def ErrorMessage():
    return ObjectContainer(
        header=u'%s' % L('Error'),
        message=u'%s' % L('An error has occurred')
    )


def NotImplemented(**kwargs):
    return ObjectContainer(
        header=u'%s' % L('Not Implemented'),
        message=u'%s' % L('This function not implemented yet')
    )


def GetRegion():
    return Prefs['region'].split('/')[1]


def GetLanguage():
    return Prefs['language'].split('/')[1]


def GetLimitForOC(oc):
    ret = int(Prefs['items_per_page'])-len(oc)
    return 8 if ret <= 0 else ret


def GetThumbFromSnippet(snippet):
    try:
        return snippet['thumbnails']['high']['url']
    except:
        return ''


def ApiGetVideos(ids=[], title=None, extended=False, **kwargs):
    return ApiRequest('videos', ApiGetParams(
        part='snippet,contentDetails',
        hl=GetLanguage(),
        id=','.join(ids),
        **kwargs
    ))


def ApiGetChannelInfo(uid):
    res = ApiRequest('channels', ApiGetParams(
        part='contentDetails,brandingSettings',
        hl=GetLanguage(),
        uid=uid,
        id=uid if uid != 'me' else None
    ))

    ret = {
        'playlists': {},
        'banner': None
    }

    if res and res['items']:
        res = res['items'][0]
        relatedPlaylists = res['contentDetails']['relatedPlaylists']

        for key in relatedPlaylists:
            # Check that the API actually returns the playlist without error
            res = ApiRequest('playlistItems', ApiGetParams(
                part='contentDetails',
                playlistId=relatedPlaylists[key]
            ),
            suppressErrorMessage=True)
            if res and len(res['items']):
                ret['playlists'][key] = relatedPlaylists[key]

        try:
            ret['banner'] = res['brandingSettings']['image']['bannerTvHighImageUrl']
        except:
            pass

    return ret


def ApiRequestErrorOccurred(response, suppressErrorMessage=False):
    errorOccurred = False
    message = ""
    try:
        if type(response) is str:
            response = JSON.ObjectFromString(response)

        if 'error' in response:
            if 'errors' in response['error']:
                for error in response['error']['errors']:
                    message += 'ApiRequest error: %s\n' % error
            else:
                message = 'ApiRequest error response empty!'

            errorOccurred = True
    except:
        if type(response) is str:
            message = 'Could not decode ApiRequest response: %s' % response
        else:
            message = 'Could not decode ApiRequest response'

        errorOccurred = True

    if errorOccurred and not suppressErrorMessage:
        Log.Error(message)

    return errorOccurred


def ApiRequest(method, params, data=None, rmethod=None, suppressErrorMessage=False):
    if not CheckToken():
        return None

    params['access_token'] = Dict['access_token']

    is_change = data or rmethod == 'DELETE'

    try:
        res = HTTP.Request(
            'https://www.googleapis.com/youtube/%s/%s?%s' % (
                YT_VERSION,
                method,
                urlencode(params)
            ),
            headers={'Content-Type': 'application/json; charset=UTF-8'},
            data=None if not data else JSON.StringFromObject(data),
            method=rmethod,
            cacheTime=0 if is_change else CACHE_1HOUR
        ).content
    except Exception as e:
        if not suppressErrorMessage:
            Log.Error('Exception: %s' % str(e))
            if hasattr(e, 'content'):
                ApiRequestErrorOccurred(e.content)
        return None

    if is_change:
        HTTP.ClearCache()
        return True

    try:
        res = JSON.ObjectFromString(res)
    except:
        return None

    if ApiRequestErrorOccurred(res, suppressErrorMessage):
        return None

    return res


def ApiGetParams(part='snippet', offset=None, limit=None, uid=None, **kwargs):
    params = {
        'part': part,
    }
    if uid is not None:
        if uid == 'me':
            params['mine'] = 'true'
        else:
            params['channelId'] = uid

    if offset:
        params['pageToken'] = offset

    if limit:
        params['maxResults'] = limit

    params.update(filter(lambda v: v[1], kwargs.items()))
    return params


def CheckToken():
    if CheckAccessData('access_token'):
        return True

    if 'refresh_token' in Dict:
        res = OAuthRequest({
            'refresh_token': Dict['refresh_token'],
            'grant_type': 'refresh_token',
        })
        if res:
            StoreAccessData(res)
            return True

    if CheckAccessData('device_code'):
        res = OAuthRequest({
            'code': Dict['device_code'],
            'grant_type': 'http://oauth.net/grant_type/device/1.0',
        })
        if res:
            StoreAccessData(res)
            return True

    return False


def ResetToken():
    del Dict['access_token']
    del Dict['refresh_token']
    del Dict['device_code']
    Dict.Reset()
    Dict.Save()


def OAuthRequest(params, rtype='token'):
    params['client_id'] = YT_CLIENT_ID
    if rtype == 'token':
        params['client_secret'] = YT_SECRET

    try:
        res = JSON.ObjectFromURL(
            'https://accounts.google.com/o/oauth2/' + rtype,
            values=params,
            cacheTime=0
        )
        if 'error' in res:
            res = False
    except:
        res = False

    return res


def CheckAccessData(key):
    return (key in Dict and Dict['expires'] >= int(time()))


def StoreAccessData(data):
    if 'expires_in' in data:
        data['expires'] = int(time()) + int(data['expires_in'])

    for key, val in data.items():
        Dict[key] = val
