# -*- coding: utf-8 -*-

# Copyright © 2012-2015 Roberto Alsina and others.

# Permission is hereby granted, free of charge, to any
# person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the
# Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the
# Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice
# shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from __future__ import print_function

import json
import mimetypes
import os
import subprocess
import sys
try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse  # NOQA
from wsgiref.simple_server import make_server
import wsgiref.util

from blinker import signal
import pyinotify
from ws4py.websocket import WebSocket
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication
from ws4py.messaging import TextMessage

from nikola.plugin_categories import Command
from nikola.utils import req_missing

LRJS_PATH = os.path.join(os.path.dirname(__file__), 'livereload.js')
MASK = pyinotify.IN_DELETE | pyinotify.IN_CREATE | pyinotify.IN_MODIFY
error_signal = signal('error')
refresh_signal = signal('refresh')


class CommandAuto(Command):
    """Start debugging console."""
    name = "auto"
    doc_purpose = "builds and serves a site; automatically detects site changes, rebuilds, and optionally refreshes a browser"
    cmd_options = [
        {
            'name': 'port',
            'short': 'p',
            'long': 'port',
            'default': 8000,
            'type': int,
            'help': 'Port nummber (default: 8000)',
        },
        {
            'name': 'address',
            'short': 'a',
            'long': 'address',
            'type': str,
            'default': '',
            'help': 'Address to bind (default: 0.0.0.0 – all local IPv4 interfaces)',
        },
        {
            'name': 'browser',
            'short': 'b',
            'type': bool,
            'help': 'Start a web browser.',
            'default': False,
        },
        {
            'name': 'ipv6',
            'short': '6',
            'long': 'ipv6',
            'default': False,
            'type': bool,
            'help': 'Use IPv6',
        },
    ]

    def _execute(self, options, args):
        """Start the watcher."""

        arguments = ['build']
        if self.site.configuration_filename != 'conf.py':
            arguments = ['--conf=' + self.site.configuration_filename] + arguments

        command_line = 'nikola ' + ' '.join(arguments)

        # Run an initial build so we are up-to-date
        subprocess.call(["nikola"] + arguments)

        port = options and options.get('port')
        self.snippet = '''<script>document.write('<script src="http://'
            + (location.host || 'localhost').split(':')[0]
            + ':{0}/livereload.js?snipver=1"></'
            + 'script>')</script>
        </head>'''.format(port)

        watched = [
            self.site.configuration_filename,
            'themes/',
            'templates/',
        ]
        for item in self.site.config['post_pages']:
            watched.append(os.path.dirname(item[0]))
        for item in self.site.config['FILES_FOLDERS']:
            watched.append(item)
        for item in self.site.config['GALLERY_FOLDERS']:
            watched.append(item)
        for item in self.site.config['LISTINGS_FOLDERS']:
            watched.append(item)

        out_folder = self.site.config['OUTPUT_FOLDER']
        if options and options.get('browser'):
            browser = True
        else:
            browser = False

        if options['ipv6']:
            dhost = '::'
        else:
            dhost = None

        host = options['address'].strip('[').strip(']') or dhost

        # Start watchers that trigger reloads
        reload_wm = pyinotify.WatchManager()
        reload_notifier = pyinotify.ThreadedNotifier(reload_wm, self.do_refresh)
        reload_notifier.start()
        reload_wm.add_watch(out_folder, MASK, rec=True)  # Watch output folders

        # Start watchers that trigger rebuilds
        rebuild_wm = pyinotify.WatchManager()
        rebuild_notifier = pyinotify.ThreadedNotifier(rebuild_wm, self.do_rebuild)
        rebuild_notifier.start()
        for p in watched:
            if os.path.exists(p):
                rebuild_wm.add_watch(p, MASK, rec=True)  # Watch input folders

        parent = self

        class Mixed(WebSocketWSGIApplication):
            """A class that supports WS and HTTP protocols in the same port."""
            def __call__(self, environ, start_response):
                uri = wsgiref.util.request_uri(environ)
                if environ.get('HTTP_UPGRADE') is None:
                    return parent.serve_static(environ, start_response)
                return super(Mixed, self).__call__(environ, start_response)

        ws = make_server('', port, server_class=WSGIServer,
                        handler_class=WebSocketWSGIRequestHandler,
                        app=Mixed(handler_cls=LRSocket))
        ws.initialize_websockets_manager()
        print("Serving on port {0}...".format(port))

        try:
            ws.serve_forever()
        except KeyboardInterrupt:
            ws.server_close()


    def do_rebuild(self, event):
        p = subprocess.Popen('nikola build', shell=True, stderr=subprocess.PIPE)
        if p.wait() != 0:
            error_signal.send(error=p.stderr.read())

    def do_refresh(self, event):
        print('REFRESHING: ', event.pathname)
        p = os.path.relpath(event.pathname, os.path.abspath(self.site.config['OUTPUT_FOLDER']))
        refresh_signal.send(path=p)

    def serve_static(self, environ, start_response):
        """Trivial static file server."""
        uri = wsgiref.util.request_uri(environ)
        print('====>', uri)
        p_uri = urlparse(uri)
        f_path = os.path.join(self.site.config['OUTPUT_FOLDER'], *p_uri.path.split('/'))
        mimetype = mimetypes.guess_type(uri)[0] or b'text/html'

        if os.path.isdir(f_path):
            f_path = os.path.join(f_path, self.site.config['INDEX_FILE'])

        if os.path.isfile(f_path):
            with open(f_path) as fd:
                start_response(b'200 OK', [(b'Content-type', mimetype)])
                return self.inject_js(mimetype, fd.read())
        elif p_uri.path == '/livereload.js':
            with open(LRJS_PATH) as fd:
                start_response(b'200 OK', [(b'Content-type', mimetype)])
                return inject_js(mimetype, fd.read())
        start_response(b'404 ERR', [])
        return ['404 {0}'.format(uri)]


    def inject_js(self, mimetype, data):
        """Inject livereload.js in HTML files."""
        if mimetype == 'text/html':
            # FIXME: use re.IGNORECASE
            data = data.replace('</head>', self.snippet, 1)
        return data


pending = []

class LRSocket(WebSocket):
    """Speak Livereload protocol."""

    def __init__(self, *a, **kw):
        refresh_signal.connect(self.notify)
        error_signal.connect(self.send_error)
        super(LRSocket, self).__init__(*a, **kw)

    def received_message(self, message):
        message = json.loads(message.data)
        print('<---', message)
        response = None
        if message['command'] == 'hello':  # Handshake
            response = {
                'command': 'hello',
                'protocols': [
                    'http://livereload.com/protocols/official-7',
                ],
                'serverName': 'nikola-livereload',
            }
        elif message['command'] == 'info':  # Someone connected
            print('****** ', 'Browser Connected: %s' % message.get('url'))
            print('****** ', 'sending {0} pending messages'.format(len(pending)))
            while pending:
                msg = pending.pop()
                print('--->', msg.data)
                self.send(msg, msg.is_binary)
        else:
            response = {
                'command': 'alert',
                'message': 'HEY',
            }
        if response is not None:
            response = json.dumps(response)
            print('--->', response)
            response = TextMessage(response)
            self.send(response, response.is_binary)

    def notify(self, sender, path):
        """Send reload requests to the client."""
        p = os.path.join('/', path)
        message = {
            'command': 'reload',
            'liveCSS': True,
            'path': p,
        }
        response = json.dumps(message)
        print('--->', p)
        response = TextMessage(response)
        if self.stream is None:  # No client connected or whatever
            pending.append(response)
        else:
            self.send(response, response.is_binary)

    def send_error(self, sender, error=None):
        """Send reload requests to the client."""
        print('ERRRRRRRR', error)
        if self.stream is None:  # No client connected or whatever
            return
        message = {
            'command': 'alert',
            'message': error,
        }
        response = json.dumps(message)
        response = TextMessage(response)
        if self.stream is None:  # No client connected or whatever
            pending.append(response)
        else:
            self.send(response, response.is_binary)
