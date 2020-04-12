import requests
import re
from flask import Flask, escape, request, redirect
from collections import namedtuple
import concurrent.futures
import threading
import time
import pdb

class BackendError(Exception):
    def __init__(self, response):
        super().__init__()
        self.response = response

cache_lock = threading.Lock()

CacheEntry = namedtuple('CacheEntry', ['posts', 'time'])

cache = {}


def get_all_posts(board_name, recent_first=True):
    r = requests.get(f'https://cyberland2.club/{board_name}/?num=999999999999999')
    try:
        posts = r.json()
    except:
        raise BackendError(r)
    return posts

def get_posts(board_name, thread_id="0", recent_first=True):
    print("get_posts", thread_id)
    r = requests.get(f'https://cyberland2.club/{board_name}/?thread={thread_id}&num=999999999999999')
    print(r.url)
    try:
        posts = r.json()
    except:
        raise BackendError(r)

    return posts

def max_id(post):
    if post['replies']:
        return max(
            max_id(reply) for reply in post['replies']
        )
    return int(post['id'])

def sort_replies(posts):
    for post in posts:
        post['replies'] = sorted(post['replies'], key=lambda x: int(x['id']))
        sort_replies(post['replies'])

def sort_ops_by_bump(posts):
    return sorted(posts, key=lambda p: max_id(p), reverse=True)

def sort_posts(posts):
    for post in posts:
        post['replies'] = sort_posts(post['replies'])
    posts = sorted(posts, key=lambda x: max_id(x), reverse=True)
    return posts

def get_posts_for_board(board_name):
    posts = get_posts(board_name)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {}
        for post in posts:
            future = executor.submit(get_posts, board_name, thread_id=post['id'], recent_first=False)
            futures[future] = post

        while futures:
            completed, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in completed:
                try:
                    replies = future.result()
                except:
                    print('cannot get replies for ', post)
                    replies = []

                post = futures[future]
                post['replies'] = []
                for reply in replies:
                    if post['id'] == reply['id']:
                        continue
                    post['replies'].append(reply)
                    new_future = executor.submit(get_posts, board_name, thread_id=reply['id'], recent_first=False)
                    futures[new_future] = reply
                del futures[future]



    posts = sort_ops_by_bump(posts)
    sort_replies(posts)

    return posts

def get_posts_for_board_simple(board_name):
    flat_posts = get_all_posts(board_name)
    posts = []
    posts_lookup = { }
    for post in flat_posts:
        post['id'] = int(post['id'])
        post['replyTo'] = int(post['replyTo']) if post['replyTo'] else 0
        post['replies'] = []
        posts_lookup[post['id']] = post

    for post in flat_posts:
        if post['replyTo'] == 0:
            posts.append(post)
        else:
            if post['replyTo'] in posts_lookup:
                posts_lookup[post['replyTo']]['replies'].append(post)
            else:
                print(f'missing post {post["replyTo"]}')
    
    
    #posts = sort_ops_by_bump(posts)
    #sort_replies(posts)
    posts = sort_posts(posts)

    return posts
    


def get_posts_cacheable(board_name):
    CACHE_STALE_SECS = 10
    with cache_lock:
        if not board_name in cache or time.time() - cache[board_name].time > CACHE_STALE_SECS:
            posts = get_posts_for_board_simple(board_name)
            cache[board_name] = CacheEntry(posts=posts, time=time.time())
        return cache[board_name].posts

Board = namedtuple('Board', ['name', 'title'])

boards = [Board('t', 'technology'), Board('n', 'news'), Board('o', 'off-topic')]

def board_by_name(name):
    for board in boards:
        if board.name == name:
            return board

def make_urls_clickable(text):
    text = re.sub(r'(https?://\w+\.\w+\S*)', r'<a href="\1" target="_blank">\1</a>', text)
    return text

app = Flask(__name__)

@app.route('/')
@app.route('/<name>')
def route_board(name=None):
    active_board = board_by_name(name)

    page = ''
    page += '''
    <html>
    <head>
    '''
    if active_board:
        page += f'<title>/{active_board.name}/ - {active_board.title} - cyberland</title>'
    else:
        page += f'<title>cyberland</title>'
    page += '''
    <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png">
    <link rel="manifest" href="/static/site.webmanifest">
    '''
    page += '''
    <style>
    body {
        color: lime;
        background: black;
        font-family: monospace;
    }
    a {
        color: lime!important;
    }
    .menu a:hover, .menu a.active {
        color: black!important;
        background: lime!important;
    }
    textarea {
        width: 500px;
        height: 200px;
        background: black;
        color: lime;
        border: 1px solid lime;
    }
    input[type=submit] {
        border: 1px solid lime;
        background: black;
        color: lime;
        font-family: monospace;
        font-size: 12pt;
        padding: 10px;
        width: 500px;
    }
    input[type=submit]:hover {
        cursor: pointer;
        color: black;
        background: lime;
        border: 1px solid black;
    }
    .post {

    }
    .content {
        padding: 10px;
        margin-bottom: 10px;
        border-left: 1px solid lime;
    }
    .replies {
        padding-left: 10px;
        border-left: 1px solid green;
    }
    </style>
    '''
    page += '''
    </head>
    <body>
    '''
    menu = []
    for board in boards:
        if board == active_board:
            menu.append(f'<a class="active" href="/{board.name}">/{board.name}/ - {board.title}</a></b>')
        else:
            menu.append(f'<a href="/{board.name}">/{board.name}/ - {board.title}</a>')
    page += '<div class="menu">'
    page += ' | '.join(menu)
    page += '</div>'

    if not active_board:
        return page

    page += f'<h1>/{active_board.name}/ - {active_board.title}</h1>'

    page += f'''
    <form method="post" action="{name}/post">
    <textarea name="content"></textarea><br>
    <input type="submit">
    </form>
    <br>
    '''

    try:
        posts = get_posts_cacheable(name)
    except BackendError as error:
        posts = []
        page += f'<h2>shit\'s fucked, backend failed with status code {error.response.status_code}</h2>'
        page += '<div style="border: 1px solid lime;">'
        page += error.response.text
        page += '</div>'
        
    
    def render_post(post):
        nonlocal page
        page += '<div class="post">'
        page += '<div class="content">'
        page += f'<a href="javascript:quote({post["id"]})" id="p{post["id"]}">#{post["id"]}</a><br>'
        content = str(escape(post['content']))
        content = make_urls_clickable(content)
        content = content.replace('\r\n', '\n').replace('\n', '<br>')
        page += content
        page += '</div>'
        page += '<div class="replies">'
        if 'replies' in post:
            for reply in post['replies']:
                render_post(reply)
        page += '</div>'
        page += '</div>'
    
    prev_post = None
    same_posts = 0
    for post in posts:
        if prev_post and prev_post['content'] == post['content']:
            same_posts += 1
            continue
        if same_posts > 1:
            page += f'<div class="post" style="color:green">({same_posts}x repeating)</div>'
        render_post(post)
        prev_post = post
        same_posts = 0
        

    page += r'''
    <script type="text/javascript">
    function quote(id) {
        let textarea = document.querySelector('textarea');
        let lines = textarea.value.split("\n");
        if (lines[0].match(/>>\d+/))
            lines.shift();
        lines.unshift(">>" + id);
        textarea.value = lines.join("\n");
    }
    </script>
    '''
    page += '</body>'
    page += '</html>'
    return page

@app.route('/<name>/post', methods=['POST'])
def route_post(name):
    board = board_by_name(name)
    if not board:
        print('no board')
        return redirect('/')
    content = request.form.get('content', None)
    if not content:
        print('no content')
        return redirect(f'/{name}')
    lines = content.split('\n', 1)
    m = re.match('>>(\d+)', lines[0])
    reply_to = '0'
    if m:
        reply_to = m.group(1)
        content = lines[1]
    data = { 'content': content, 'replyTo': reply_to }
    r = requests.post(f'https://cyberland2.club/{name}/', data=data)
    with cache_lock:
        if name in cache:
            del cache[name]
    return redirect(f'/{name}')

if __name__ == '__main__':
    app.run(debug=True)