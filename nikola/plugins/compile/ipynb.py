# -*- coding: utf-8 -*-

# Copyright © 2013-2015 Damián Avila and others.

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

"""Implementation of compile_html based on nbconvert."""

from __future__ import unicode_literals, print_function
import io
import os
import sys

try:
    import IPython
    from IPython.nbconvert.exporters import HTMLExporter
    if IPython.version_info[0] >= 3:     # API changed with 3.0.0
        from IPython import nbformat
        current_nbformat = nbformat.current_nbformat
    else:
        import IPython.nbformat.current as nbformat
        current_nbformat = 'json'

    from IPython.config import Config
    flag = True
except ImportError:
    flag = None

from nikola.plugin_categories import PageCompiler
from nikola.utils import makedirs, req_missing, get_logger


class CompileIPynb(PageCompiler):
    """Compile IPynb into HTML."""

    name = "ipynb"
    demote_headers = True
    default_kernel = 'python2' if sys.version_info[0] == 2 else 'python3'

    def set_site(self, site):
        self.logger = get_logger('compile_ipynb', site.loghandlers)
        super(CompileIPynb, self).set_site(site)

    def compile_html(self, source, dest, is_two_file=True):
        if flag is None:
            req_missing(['ipython[notebook]>=1.1.0'], 'build this site (compile ipynb)')
        makedirs(os.path.dirname(dest))
        HTMLExporter.default_template = 'basic'
        c = Config(self.site.config['IPYNB_CONFIG'])
        exportHtml = HTMLExporter(config=c)
        with io.open(dest, "w+", encoding="utf8") as out_file:
            with io.open(source, "r", encoding="utf8") as in_file:
                nb_json = nbformat.read(in_file, current_nbformat)
            (body, resources) = exportHtml.from_notebook_node(nb_json)
            out_file.write(body)

    def read_metadata(self, post, file_metadata_regexp=None, unslugify_titles=False, lang=None):
        """read metadata directly from ipynb file.

        As ipynb file support arbitrary metadata as json, the metadata used by Nikola
        will be assume to be in the 'nikola' subfield.
        """
        if flag is None:
            req_missing(['ipython[notebook]>=1.1.0'], 'build this site (compile ipynb)')
        source = post.source_path
        with io.open(source, "r", encoding="utf8") as in_file:
            nb_json = nbformat.read(in_file, current_nbformat)
        # Metadata might not exist in two-file posts or in hand-crafted
        # .ipynb files.
        return nb_json.get('metadata', {}).get('nikola', {})

    def create_post(self, path, **kw):
        if flag is None:
            req_missing(['ipython[notebook]>=1.1.0'], 'build this site (compile ipynb)')
        content = kw.pop('content', None)
        onefile = kw.pop('onefile', False)
        kernel = kw.pop('ipython_kernel', None)
        # is_page is not needed to create the file
        kw.pop('is_page', False)

        metadata = {}
        metadata.update(self.default_metadata)
        metadata.update(kw)

        makedirs(os.path.dirname(path))

        if IPython.version_info[0] >= 3:
            nb = nbformat.v4.new_notebook()
            nb["cells"] = [nbformat.v4.new_code_cell(content)]
        else:
            nb = nbformat.v3.nbbase.new_notebook()
            nb["cells"] = [nbformat.v3.nbbase.new_code_cell(content)]

        if onefile:
            nb["metadata"]["nikola"] = metadata

        if kernel is None:
            kernel = self.default_kernel
            self.logger.notice('No kernel specified, assuming "{0}".'.format(kernel))

        if kernel not in IPYNB_KERNELS:
            self.logger.error('Unknown kernel "{0}". Maybe you mispelled it?'.format(kernel))
            self.logger.info("Available kernels: {0}".format(", ".join(sorted(IPYNB_KERNELS))))
            raise Exception('Unknown kernel "{0}"'.format(kernel))

        nb["metadata"].update(IPYNB_KERNELS[kernel])

        with io.open(path, "w+", encoding="utf8") as fd:
            if IPython.version_info[0] >= 3:
                nbformat.write(nb, fd, 4)
            else:
                nbformat.write(nb, fd, 'ipynb')

# python2 nb metadata info

IPYNB_KERNELS = {
    "python2": {
        "kernelspec": {
            "display_name": "Python 2",
            "language": "python",
            "name": "python2"
        },
        "language_info": {
            "codemirror_mode": {
                "name": "ipython",
                "version": 2
            },
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython2",
            "version": "2.7.10"
        },
    },

    "python3": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "codemirror_mode": {
                "name": "ipython",
                "version": 3
            },
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.4.3"
        },
    },

    "julia": {
        "kernelspec": {
            "display_name": "Julia 0.3.2",
            "language": "julia",
            "name": "julia-0.3"
        },
        "language_info": {
            "name": "julia",
            "version": "0.3.2"
        }
    },

    "r": {
        "kernelspec":  {
            "display_name": "R",
            "language": "R",
            "name": "ir"
        },
        "language_info": {
            "codemirror_mode": "r",
            "file_extension": ".r",
            "mimetype": "text/x-r-source",
            "name": "R",
            "pygments_lexer": "r",
            "version": "3.1.3"
        }
    },
    }
