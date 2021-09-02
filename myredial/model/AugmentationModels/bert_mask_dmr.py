from model.utils import *
from dataloader.util_func import *


class BERTMaskAugmentationDMRModel(nn.Module):

    '''DMR: dynamic mask ratio'''

    def __init__(self, **args):
        super(BERTMaskAugmentationDMRModel, self).__init__()
        self.args = args
        model = args['pretrained_model']
        self.model = BertForMaskedLM.from_pretrained(model)
        self.model.resize_token_embeddings(self.model.config.vocab_size+1)

        self.vocab = BertTokenizer.from_pretrained(model)
        self.special_tokens = self.vocab.convert_tokens_to_ids(['[PAD]', '[SEP]', '[CLS]'])
        self.mask, self.pad = self.vocab.convert_tokens_to_ids(['[MASK]', '[PAD]'])
        self.da_num = args['augmentation_t']
        self.ratio_list = np.arange(self.args['min_masked_lm_prob'], self.args['max_masked_lm_prob'], (self.args['max_masked_lm_prob']-self.args['min_masked_lm_prob'])/self.da_num)
        assert len(self.ratio_list) == self.da_num
    
    @torch.no_grad()
    def forward(self, batch):
        inpt = batch['ids']
        rest = []

        if batch['full'] is False:
            response = batch['response']
        else:
            response = []
            for l, res in zip(batch['length'], batch['response']):
                response.extend([res]*l)
        for i in range(self.da_num):
            ids = []
            for ii in deepcopy(inpt):
                mask_sentence_only_mask(ii, self.args['min_mask_num'], self.args['max_mask_num'], self.ratio_list[i], mask=self.mask, vocab_size=len(self.vocab), special_tokens=self.special_tokens)
                ii = torch.LongTensor(ii)
                ids.append(ii)
            ids = pad_sequence(ids, batch_first=True, padding_value=self.pad)
            mask = generate_mask(ids)
            ids, mask = to_cuda(ids, mask)

            logits = self.model(
                input_ids=ids,
                attention_mask=mask,
            )[0]    # [B, S, V]
            sent = self.generate_text(ids, F.softmax(logits, dim=-1), response)    # [B] list
            rest.append(sent)
        # rest: K*[B] -> B*[K]
        if batch['full'] is False:
            rest_ = []
            for i in range(len(batch['response'])):
                rest_.append([item[i] for item in rest])
        else:
            idx, length = 0, batch['length']
            rest_ = []
            for i in range(len(batch['context'])):
                l = length[i]
                k = list(chain(*[item[idx:idx+l] for item in rest]))
                rest_.append(k)
                idx += l
        return rest_

    def generate_text(self, ids, logits, responses):
        sentences = []
        for item, inpt, res in zip(logits, ids, responses):
            inpt = inpt.tolist()
            tokens_ = torch.multinomial(item, num_samples=1).tolist()    # [S, K]
            tokens_ = [token[0] for token in tokens_]
            ts = [t if ot == self.mask else ot for t, ot in zip(tokens_, inpt) if ot not in self.special_tokens and t not in self.special_tokens]
            string = [self.vocab.convert_ids_to_tokens(t) for t in ts]
            string = ''.join(string)
            if string != res:
                sentences.append(string)
            else:
                sentences.append('')
        return sentences