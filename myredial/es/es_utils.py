from tqdm import tqdm
import ipdb
import json
from elasticsearch import Elasticsearch, helpers


class ESBuilder:

    def __init__(self, index_name, create_index=False, q_q=False):
        self.es = Elasticsearch(hosts=['localhost:9200'])
        self.index = index_name
        self.q_q = q_q

        if create_index:
            if q_q is False:
                mapping = {
                    'properties': {
                        'response': {
                            'type': 'text',
                            'analyzer': 'ik_max_word',
                            'search_analyzer': 'ik_max_word',
                        },
                        'keyword': {
                            'type': 'keyword'
                        }
                    }
                }
            else:
                mapping = {
                    'properties': {
                        'context': {
                            'type': 'text',
                            'analyzer': 'ik_max_word',
                            'search_analyzer': 'ik_max_word',
                        },
                        'response': {
                            'type': 'keyword',
                        }
                    }
                }
            if self.es.indices.exists(index=self.index):
                self.es.indices.delete(index=self.index)
            rest = self.es.indices.create(index=self.index)
            rest = self.es.indices.put_mapping(body=mapping, index=self.index)

    def insert(self, pairs):
        count = self.es.count(index=self.index)['count']
        actions = []
        for i, (q, a) in enumerate(tqdm(pairs)):
            if self.q_q:
                actions.append({
                    '_index': self.index,
                    '_id': i + count,
                    'context': q,
                    'response': a,
                })
            else:
                actions.append({
                    '_index': self.index,
                    '_id': i + count,
                    'response': a,
                    'keyword': a,
                })
        helpers.bulk(self.es, actions)
        print(f'[!] database size: {self.es.count(index=self.index)["count"]}')


class ESSearcher:

    def __init__(self, index_name, q_q=False):
        self.es = Elasticsearch(hosts=['localhost:9200'])
        self.index = index_name
        self.q_q = q_q

    def msearch(self, queries, topk=10, limit=128):
        # limit the queries length
        queries = [query[-limit:] for query in queries]

        search_arr = []
        for query in queries:
            search_arr.append({'index': self.index})
            if self.q_q:
                search_arr.append({
                    'query': {
                        'match': {
                            'context': query
                        }
                    },
                    'collapse': {
                        'field': 'response'    
                    },
                    'size': topk,
                })
            else:
                search_arr.append({
                    'query': {
                        'match': {
                            'response': query
                        }
                    },
                    'collapse': {
                        'field': 'keyword'    
                    },
                    'size': topk,
                })

        # prepare for searching
        request = ''
        for each in search_arr:
            request += f'{json.dumps(each)} \n'
        rest = self.es.msearch(body=request)

        results = []
        for each in rest['responses']:
            p = []
            try:
                for utterance in each['hits']['hits']:
                    p.append(utterance['fields']['response'][0])
            except:
                ipdb.set_trace()
            results.append(p)
        return results

    def search(self, query, topk=10):
        if self.q_q:
            dsl = {
                'query': {
                    'match': {
                        'context': query
                    }
                },
                'collapse': {
                    'field': 'response'
                }
            }
        else:
            dsl = {
                'query': {
                    'match': {
                        'response': query
                    }
                },
                'collapse': {
                    'field': 'keyword'
                }
            }
        hits = self.es.search(index=self.index, body=dsl, size=topk)['hits']['hits']
        rest = []
        for h in hits:
            rest.append(h['_source']['response'])
        return rest


def load_qa_pair(path, lang='zh'):
    with open(path) as f:
        dataset = []
        for line in f.readlines():
            utterances = line.strip().split('\t')
            if int(utterances[0]) == 0:
                continue
            if lang == 'zh':
                utterances = [''.join(i.split()) for i in utterances]
            q = ' '.join(utterances[1:-1])
            a = utterances[-1]
            dataset.append((q, a))
    return dataset