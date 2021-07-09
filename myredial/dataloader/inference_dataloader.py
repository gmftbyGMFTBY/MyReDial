from header import *
from .utils import *

class BERTDualInferenceDataset(Dataset):
    
    def __init__(self, vocab, path, **args):
        self.args = args
        self.vocab = vocab
        self.pad = self.vocab.convert_tokens_to_ids('[PAD]')
        suffix = args['tokenizer'].replace('/', '_')
        self.pp_path = f'{os.path.splitext(path)[0]}_{suffix}.pt'
        if os.path.exists(self.pp_path):
            self.data = torch.load(self.pp_path)
            print(f'[!] load preprocessed file from {self.pp_path}')
            return None
        # except the response in the train dataset, test dataset responses are included for inference test
        # for inference[gray mode] do not use the test set responses
        train_path = f'{os.path.split(path)[0]}/train.txt'
        responses = read_response_data(train_path, lang=self.args['lang'])
        test_path = f'{os.path.split(path)[0]}/test.txt'
        test_responses = read_response_data(test_path, lang=self.args['lang'])
        responses = list(set(responses + test_responses))
        self.data = []
        for res in tqdm(responses):
            item = self.vocab.encode(res)
            rids = self._length_limit(item)
            self.data.append({
                'ids': rids, 
                'text': res
            })
                
    def _length_limit(self, ids):
        if len(ids) > self.args['max_len']:
            ids = ids[:self.args['max_len']]
        return ids
                
    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        bundle = self.data[i]
        rid = torch.LongTensor(bundle['ids'])
        rid_text = bundle['text']
        return rid, rid_text

    def save(self):
        data = torch.save(self.data, self.pp_path)
        print(f'[!] save preprocessed dataset into {self.pp_path}')
        
    def generate_mask(self, ids):
        attn_mask_index = ids.nonzero().tolist()   # [PAD] IS 0
        attn_mask_index_x, attn_mask_index_y = [i[0] for i in attn_mask_index], [i[1] for i in attn_mask_index]
        attn_mask = torch.zeros_like(ids)
        attn_mask[attn_mask_index_x, attn_mask_index_y] = 1
        return attn_mask
        
    def collate(self, batch):
        rid = [i[0] for i in batch]
        rid_text = [i[1] for i in batch]
        rid = pad_sequence(rid, batch_first=True, padding_value=self.pad)
        rid_mask = self.generate_mask(rid)
        if torch.cuda.is_available():
            rid, rid_mask = rid.cuda(), rid_mask.cuda()
        return {
            'ids': rid, 
            'mask': rid_mask, 
            'text': rid_text
        }


class BERTDualCLInferenceDataset(Dataset):

    '''for dual-bert-fusion model, which need response and context to generate the response representations'''
    
    def __init__(self, vocab, path, **args):
        self.args = args
        self.vocab = vocab
        self.max_context_turn_size = args['max_context_turn']
        self.pad = self.vocab.convert_tokens_to_ids('[PAD]')
        suffix = args['tokenizer'].replace('/', '_')
        self.pp_path = f'{os.path.splitext(path)[0]}_cl_{self.max_context_turn_size}_{suffix}.pt'
        if os.path.exists(self.pp_path):
            self.data = torch.load(self.pp_path)
            print(f'[!] load preprocessed file from {self.pp_path}')
            return None
        # except the response in the train dataset, test dataset responses are included for inference test
        responses = read_cl_response_data(path, lang=self.args['lang'], max_context_turn=self.max_context_turn_size)
        test_path = f'{os.path.split(path)[0]}/test.txt'
        test_responses = read_cl_response_data(test_path, lang=self.args['lang'], max_context_turn=self.max_context_turn_size)
        for res, ctxs in test_responses.items():
            if res in responses:
                responses[res].extend(ctxs)
            else:
                responses[res] = ctxs
        self.data = []
        for res, ctxs in tqdm(responses.items()):

            # context cut

            item = self.vocab.batch_encode_plus([res] + ctxs)
            res_ids = item['input_ids'][0]
            ctx_ids = item['input_ids'][1:]
            rids = self._length_limit_res(res_ids)
            cids = [self._length_limit(i) for i in ctx_ids]
            self.data.append({
                'ids': rids, 
                'cids': cids,
                'text': res
            })
                
    def _length_limit_res(self, ids):
        if len(ids) > self.args['res_max_len']:
            ids = ids[:self.args['res_max_len']]
        return ids
    
    def _length_limit(self, ids):
        if len(ids) > self.args['max_len']:
            ids = [ids[0]] + ids[-(self.args['max_len']-1):]
        return ids
                
    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        bundle = self.data[i]
        rid = torch.LongTensor(bundle['ids'])
        rid_text = bundle['text']
        cid = torch.LongTensor(random.choice(bundle['cids']))
        return rid, rid_text, cid

    def save(self):
        data = torch.save(self.data, self.pp_path)
        print(f'[!] save preprocessed dataset into {self.pp_path}')
        
    def generate_mask(self, ids):
        attn_mask_index = ids.nonzero().tolist()   # [PAD] IS 0
        attn_mask_index_x, attn_mask_index_y = [i[0] for i in attn_mask_index], [i[1] for i in attn_mask_index]
        attn_mask = torch.zeros_like(ids)
        attn_mask[attn_mask_index_x, attn_mask_index_y] = 1
        return attn_mask
        
    def collate(self, batch):
        rid = [i[0] for i in batch]
        rid_text = [i[1] for i in batch]
        cid = [i[2] for i in batch]

        rid = pad_sequence(rid, batch_first=True, padding_value=self.pad)
        cid = pad_sequence(cid, batch_first=True, padding_value=self.pad)
        rid_mask = self.generate_mask(rid)
        cid_mask = self.generate_mask(cid)
        if torch.cuda.is_available():
            rid, rid_mask = rid.cuda(), rid_mask.cuda()
            cid, cid_mask = cid.cuda(), cid_mask.cuda()
        return {
            'ids': rid, 
            'mask': rid_mask, 
            'cid': cid,
            'cid_mask': cid_mask,
            'text': rid_text
        }
