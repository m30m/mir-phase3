import json
import os
from os import path
import numpy as np

from elasticsearch import Elasticsearch
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

import crawler.settings as settings
from crawler.spiders.blog_spider import BlogSpider

es = Elasticsearch(hosts=['127.0.0.1'])
INDEX_NAME = 'blog_index'
RESULT_DIR = 'output'


def normalize_blog_url(url):
    try:
        return url[:(url.index('blog.ir') + len('blog.ir'))]
    except ValueError:
        return None


def convert_blog(item, post_comments):
    blog_object = {}
    blog_object['url'] = normalize_blog_url(item['blog_url'])
    if not blog_object['url']:
        return None
    blog_object['title'] = item['blog_name']
    blog_object['posts'] = []
    for i in range(1, 10):
        if ('post_content_%d' % i) in item:
            post_object = {}
            post_object['post_content'] = item['post_content_%d' % i]
            post_object['post_url'] = item['post_url_%d' % i]
            post_object['post_title'] = item['post_title_%d' % i]
            post_object['post_comments'] = []
            for comment in post_comments.get(post_object['post_url'], []):
                normalized_comment_url = normalize_blog_url(comment)
                if normalized_comment_url:
                    post_object['post_comments'].append({'comment_url': normalized_comment_url})
            blog_object['posts'].append(post_object)
    blog_object = {'blog': blog_object}
    # print(json.dumps(blog_object,indent=2,ensure_ascii=False))
    return blog_object


def read_results():
    blog_jsons = []
    post_comments = {}
    for json_file in os.listdir(RESULT_DIR):
        if json_file.endswith('.json'):
            uri = path.join(RESULT_DIR, json_file)
            item = json.loads(open(uri).read())
            if item['type'] == 'post':
                post_comments[item['post_url']] = item['comment_urls']
            else:
                blog_jsons.append(item)
    return blog_jsons, post_comments


def delete_index():
    es.indices.delete(index=INDEX_NAME)


def fill_index():
    blog_jsons, post_comments = read_results()
    blog_objects = [convert_blog(item, post_comments) for item in blog_jsons]
    blog_objects = [blog for blog in blog_objects if blog]
    for item in blog_objects:
        es.index(index=INDEX_NAME, doc_type="blog", id=item['blog']['url'], body=item)
    es.indices.create(index=INDEX_NAME, ignore=400)


def compute_blog_mapping(blog_objects):
    mapping = {}
    reverse_mapping = []
    ctr = 0
    for blog in blog_objects:
        mapping[blog['blog']['url']] = ctr
        reverse_mapping.append(blog['blog']['url'])
        ctr += 1
    return mapping, reverse_mapping, ctr


def compute_page_rank(blog_objects, alpha):
    mapping, reverse_mapping, n_blogs = compute_blog_mapping(blog_objects)
    p_matrix = np.zeros(shape=(n_blogs, n_blogs), dtype=float)
    for blog in blog_objects:
        this_blog = mapping[blog['blog']['url']]
        for post in blog['blog']['posts']:
            for comment in post['post_comments']:
                if comment['comment_url'] in mapping:
                    neighbor_blog = mapping[comment['comment_url']]
                    p_matrix[neighbor_blog, this_blog] = 1
    for i in range(n_blogs):
        if p_matrix[i].sum() == 0:
            p_matrix[i] = np.ones(n_blogs) / n_blogs
        else:
            p_matrix[i] = (p_matrix[i] / p_matrix[i].sum()) * (1 - alpha) + (np.ones(n_blogs) / n_blogs) * alpha
    eigenvals, eigenvecs = np.linalg.eig(p_matrix.T)
    left_pricipal_eigen_vec = np.real(eigenvecs[:, eigenvals.argmax()].T)
    page_rank = left_pricipal_eigen_vec / left_pricipal_eigen_vec.sum()
    return dict(zip(reverse_mapping, page_rank))


def add_page_rank(alpha=0.1):
    blog_jsons, post_comments = read_results()
    blog_objects = [convert_blog(item, post_comments) for item in blog_jsons]
    blog_objects = [blog for blog in blog_objects if blog]
    page_rank = compute_page_rank(blog_objects, alpha)
    for url in page_rank:
        es.update(index=INDEX_NAME, doc_type='blog', id=url, body={'doc': {'blog': {'page_rank': page_rank[url]}}})


def search(query, weights={}, pr_weight=0):
    n_docs = es.count(index=INDEX_NAME, doc_type='blog')['count']
    body_query = {
        'query': {
            'function_score': {
                'query': {
                    'bool': {
                        'should': []
                    }
                },
                'functions': [
                    {
                        'field_value_factor': {
                            'field': 'blog.page_rank',
                            'factor': n_docs * pr_weight,
                        },
                    },
                ],
                'boost_mode': 'sum',
            }
        }
    }
    for field in query:
        body_query['query']['function_score']['query']['bool']['should'].append({
            'match': {
                'blog.' + field: {
                    'query': query[field],
                    'boost': weights.get(field, 1),
                },
            },
        })
    res = es.search(index=INDEX_NAME, doc_type='blog', body=body_query)
    return [(hit['_source']['blog']['url'], hit['_source']['blog']['page_rank'],
             hit['_score']) for hit in res['hits']['hits']]


def init_elastic():
    global ES_HOST, es
    ES_HOST = input('Enter elastic host: (default is "127.0.0.1")') or '127.0.0.1'
    es = Elasticsearch(hosts=[ES_HOST])


if __name__ == '__main__':
    while True:
        print('What do you want to do?')
        print('1) Crawl blogs')
        print('2) Delete Index')
        print('3) Create Index')
        print('4) Calculate PageRank')
        print('5) Search')
        print('6) Show Blog')
        print('Q) Quit')
        x = input('')
        if x == '1':
            crawler_settings = Settings()
            crawler_settings.setmodule(settings)
            INITIAL_URL_FILE = input('Enter start urls file path: (default is "urls.txt")') or 'urls.txt'
            BLOG_LIMIT = input('Enter blog limit: (default is 10)') or 10
            POST_PER_RSS = input('Enter number of posts to crawl per blog rss: (default is  5)') or 5
            RSS_PER_POST = input('Enter number of new blogs to crawl from post: (default is  5)') or 5
            crawler_settings.set('INITIAL_URL_FILE', INITIAL_URL_FILE)
            crawler_settings.set('BLOG_LIMIT', BLOG_LIMIT)
            crawler_settings.set('POST_PER_RSS', POST_PER_RSS)
            crawler_settings.set('RSS_PER_POST', RSS_PER_POST)
            process = CrawlerProcess(settings=crawler_settings)
            process.crawl(BlogSpider)
            process.start()
        elif x == '2':
            delete_index()
        elif x == '3':
            RESULT_DIR = input('Enter jsons directory path: (default is "output")') or 'output'
            init_elastic()
            fill_index()
        elif x == '4':
            init_elastic()
            ALPHA = float(input('Enter alpha for page rank: (default is 0.1)')) or 0.1
            add_page_rank(alpha=ALPHA)
        elif x == '5':
            fields = ['url', 'title', 'posts.post_title', 'posts.post_content']
            queries = {}
            weights = {}
            for field in fields:
                q_val = input('Enter filter for %s: (Press Enter to skip this field)\n' % field)
                if q_val:
                    queries[field] = q_val
                    try:
                        w_val = float(
                            input('Enter weight for filter %s: (Press Enter for default weight 1.0)\n' % field))
                        weights[field] = w_val
                    except ValueError:
                        pass
            try:
                pr_weight = float(input('Enter weight for page rank: (Press Enter for default weight 1.0)\n'))
            except:
                pr_weight = 1
            print(search(query=queries, weights=weights, pr_weight=pr_weight))
        elif x == '6':
            url = input('Enter URL (e.g https://salamfereshte.blog.ir):')
            print(
                json.dumps(es.get(index=INDEX_NAME, doc_type='blog', id=url)['_source'], indent=2, ensure_ascii=False))
        elif x == 'Q':
            break
        else:
            print('Not a valid input')
