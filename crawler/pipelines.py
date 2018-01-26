# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://doc.scrapy.org/en/latest/topics/item-pipeline.html
import json


class JsonWriterPipeline(object):

    def open_spider(self, spider):
        self.counter = 1

    def close_spider(self, spider):
        pass

    def process_item(self, item, spider):
        output = json.dumps(item, indent=4, sort_keys=True, ensure_ascii=False) + '\n'
        if item['type'] == 'blog':
            output_file = open('output/blog-%d.json' % self.counter, 'w')
        else:
            output_file = open('output/post-%d.json' % self.counter, 'w')
        output_file.write(output)
        output_file.close()
        self.counter += 1
        # return item
