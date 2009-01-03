#!/usr/bin/env python
import models
from django.core.urlresolvers import reverse
from itertools import groupby
from django.template.defaultfilters import slugify
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic


from techblog import broadcast
import time
import datetime
import re
#from BeautifulSoup import BeautifulSoup

try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

def collate_archives(blog):

    """Groups the posts for a blog by month.

    blog -- A Blog model

    Returns a list of tuples containing the year (as an integer),
    the month (integer) and the number of posts in that month (integer).

    """

    posts = blog.posts().values('display_time').order_by("-display_time")

    def count_iterable(i):
        return sum(1 for _ in i)

    def year_month(post):
        display_time = post['display_time']
        return (display_time.year, display_time.month)

    def month_details(year, month, post_group):
        url = reverse("blog_month", kwargs=dict(blog_slug=blog.slug, year=year, month=month))
        return url, year, month, count_iterable(post_group)

    months = [month_details(year, month, post_group) for (year, month),post_group in groupby(posts, year_month)]

    years = [(year,list(months)) for (year, months) in groupby(months, lambda m:m[1])]

    return years


def import_wxr(blog_slug, wxr_file):


    namespaces = """
	xmlns:excerpt="http://wordpress.org/export/1.0/excerpt/"
	xmlns:content="http://purl.org/rss/1.0/modules/content/"
	xmlns:wfw="http://wellformedweb.org/CommentAPI/"
	xmlns:dc="http://purl.org/dc/elements/1.1/"
	xmlns:wp="http://wordpress.org/export/1.0/"
"""

    content_ns = "http://purl.org/rss/1.0/modules/content/"
    wp_ns = "http://wordpress.org/export/1.0/"

    blog = models.Blog.objects.get(slug=blog_slug)

    wxr = ET.parse(wxr_file)

    items = wxr.findall(".//item")

    def get_text(item, name, ns=None, default=""):
        if ns is None:
            el = item.find(".//%s" % name)
        else:
            el = item.find(".//{%s}%s" % (ns, name))
        if el is not None:
            if el.text is None:
                return default
            return el.text
        return default

    pre_re = re.compile(r'<pre lang="(\w+)">(.*?)<\/pre>', re.S)
    def fix_html(html):

        html = html.replace('<p>', '')
        html = html.replace('</p>', '')
        html = html.replace('&gt;&gt;&gt;', '>>>')

        def repl(match):
            return "\n\n{..code}\n{..language=%s}\n%s\n\n{..html_paragraphs}\n" % (match.group(1), match.group(2))
        html = pre_re.sub(repl, html)

        html = html.replace("<pre>", "\n\n{..code}\n")
        html = html.replace("</pre>", "\n\n{..html_paragraphs}\n")
        html = html.replace("<h2>", "<h3>")
        html = html.replace("</h2>", "</h3>")

        return "{..html_paragraphs}\n" + html


    if items is not None:

        for item in items:

            post_type = get_text(item, "post_type", wp_ns)
            if post_type!="post":
                continue

            status = get_text(item, 'status')
            if status.lower() == "draft":
                continue

            guid = get_text(item, 'guid')
            title = get_text(item, 'title')

            if not title or not guid:
                continue
            slug = slugify(title)
            content = get_text(item, 'encoded', content_ns)

            pub_date = get_text(item, 'pubDate')
            pub_date = datetime.datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S +0000")
            #pub_date = datetime.datetime(*pub_date)


            catagories = set(category.text for category in item.findall(".//category"))
            tags = ",".join(catagories)

            #content = BeautifulSoup(content).prettify()
            #content = tidy.parseString(content)

            content = fix_html(content)


            try:
                new_post = models.Post.objects.get(guid=guid)
            except models.Post.DoesNotExist:
                new_post = models.Post()

            new_post_data = dict(   blog=blog,
                                    title=title,
                                    slug=slug,
                                    guid=guid,
                                    published=True,
                                    allow_comments=True,

                                    created_time=pub_date,
                                    edit_time=pub_date,
                                    display_time=pub_date,

                                    tags_text=tags,
                                    content=content,
                                    content_markup_type="epostmarkup" )
            for k, v in new_post_data.iteritems():
                setattr(new_post, k, v)
            new_post.save()

            comments = item.findall(".//{%s}comment" % wp_ns)

            if comments is not None:
                for comment in comments:

                    if get_text(comment, "comment_approved", wp_ns) != "1":
                        continue

                    name = get_text(comment, "comment_author", wp_ns)
                    email = get_text(comment, "comment_author_email", wp_ns)
                    url = get_text(comment, "comment_author_url", wp_ns)
                    content = get_text(comment, "comment_content", wp_ns)
                    date = get_text(comment, "comment_date", wp_ns)

                    date = datetime.datetime.strptime(date, "%Y-%m-%d %H:%M:%S")

                    ct = ContentType.objects.get_for_model(new_post)
                    ct_id = ".".join( (ct.app_label, ct.model) )

                    broadcast.call.comment(object_id = new_post.id,
                                           visible=True,
                                           moderated=True,
                                           created_time=date,
                                           name = name,
                                           email=email,
                                           url=url,
                                           content=content,
                                           content_markup_type="comment_bbcode",
                                           content_type=ct)
