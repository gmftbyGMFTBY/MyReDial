from model.utils import *

'''Speraker-aware Bert Cross-encoder'''

class SABERTRetrieval(nn.Module):

    def __init__(self, model='bert-base-chinese'):
        super(SABERTRetrieval, self).__init__()
        self.model = BertModel.from_pretrained(model)
        self.model.resize_token_embeddings(self.model.config.vocab_size+1)
        self.head = nn.Linear(768, 2)
        self.speaker_embedding = nn.Embedding(2, 768)

    def forward(self, inpt, token_type_ids, speaker_type_ids, attn_mask):
        word_embeddings = self.model.embeddings(inpt)    # [B, S, 768]
        speaker_embedding = self.speaker_embedding(speaker_type_ids)   # [B, S, 768]
        word_embeddings += speaker_embedding
        output = self.model(
            input_ids=None,
            attention_mask=attn_mask,
            token_type_ids=token_type_ids,
            inputs_embeds=word_embeddings,
        )[0]    # [B, S, E]
        logits = self.head(output[:, 0, :])    # [B, H] -> [B, 2]
        return logits

    def load_bert_model(self, state_dict):
        new_state_dict = OrderedDict()
        for k, v in state_dict.items():
            new_state_dict[k] = v
        new_state_dict['embeddings.position_ids'] = torch.arange(512).expand((1, -1))
        self.model.load_state_dict(new_state_dict)

    
class SABERTFTAgent(RetrievalBaseAgent):

    def __init__(self, args):
        super(SABERTFTAgent, self).__init__()
        self.args = args
        self.set_test_interval()
        self.vocab = BertTokenizer.from_pretrained(self.args['tokenizer'])
        self.model = SABERTRetrieval(self.args['model'])
        self.load_checkpoint()
        self.criterion = nn.CrossEntropyLoss()
        if torch.cuda.is_available():
            self.model.cuda()
        self.set_optimizer_scheduler_ddp()
        self.show_parameters(self.args)
        
    def load_bert_model(self, path):
        state_dict = torch.load(path, map_location=torch.device('cpu'))
        self.model.load_bert_model(state_dict)
        print(f'[!] load pretrained BERT model from {path}')

    def train_model(self, train_iter, test_iter, recoder=None, idx_=0):
        self.model.train()
        total_loss, batch_num, correct, s = 0, 0, 0, 0
        pbar = tqdm(train_iter)
        correct, s = 0, 0
        for idx, batch in enumerate(pbar):
            ids, tids, sids, mask, label = batch
            self.optimizer.zero_grad()
            with autocast():
                output = self.model(ids, tids, sids, mask)    # [B, 2]
                loss = self.criterion(
                    output, 
                    label.view(-1),
                )
            self.scaler.scale(loss).backward()
            self.scaler.unscale_(self.optimizer)
            clip_grad_norm_(self.model.parameters(), self.args['grad_clip'])
            self.scaler.step(self.optimizer)
            self.scaler.update()
            self.scheduler.step()

            total_loss += loss.item()
            batch_num += 1

            if batch_num in self.args['test_step']:
                self.test_now(test_iter, recoder)
            
            now_correct = torch.max(F.softmax(output, dim=-1), dim=-1)[1]    # [batch]
            now_correct = torch.sum(now_correct == label).item()
            correct += now_correct
            s += len(label)
            
            recoder.add_scalar(f'train-epoch-{idx_}/Loss', total_loss/batch_num, idx)
            recoder.add_scalar(f'train-epoch-{idx_}/RunLoss', loss.item(), idx)
            recoder.add_scalar(f'train-epoch-{idx_}/Acc', correct/s, idx)
            recoder.add_scalar(f'train-epoch-{idx_}/RunAcc', now_correct/len(label), idx)
            pbar.set_description(f'[!] train loss: {round(loss.item(), 4)}|{round(total_loss/batch_num, 4)}; acc: {round(now_correct/len(label), 4)}|{round(correct/s, 4)}')
        recoder.add_scalar(f'train-whole/Loss', total_loss/batch_num, idx_)
        recoder.add_scalar(f'train-whole/Acc', correct/s, idx_)
        return round(total_loss / batch_num, 4)
    
    @torch.no_grad()
    def test_model(self, test_iter):
        self.model.eval()
        pbar = tqdm(test_iter)
        total_mrr, total_prec_at_one, total_map = 0, 0, 0
        total_examples, total_correct = 0, 0
        k_list = [1, 2, 5, 10]
        for idx, batch in enumerate(pbar):
            ids, tids, sids, mask, label = batch
            batch_size = len(ids)
            scores = self.model(ids, tids, sids, mask)[:, 1].tolist()
            rank_by_pred, pos_index, stack_scores = \
                    calculate_candidates_ranking(
                        np.array(scores), 
                        np.array(label.cpu().tolist()),
                        10,
                    )
            num_correct = logits_recall_at_k(pos_index, k_list)
            if self.args['dataset'] in ["douban"]:
                total_prec_at_one += precision_at_one(rank_by_pred)
                total_map += mean_average_precision(pos_index)
                for pred in rank_by_pred:
                    if sum(pred) == 0:
                        total_examples -= 1
            total_mrr += logits_mrr(pos_index)
            total_correct = np.add(total_correct, num_correct)
            total_examples += math.ceil(label.size()[0] / 10)
        avg_mrr = float(total_mrr / total_examples)
        avg_prec_at_one = float(total_prec_at_one / total_examples)
        avg_map = float(total_map / total_examples)
        
        for i in range(len(k_list)):
            print(f"R10@{k_list[i]}: {round(((total_correct[i] / total_examples) * 100), 2)}")
        print(f"MRR: {round(avg_mrr, 4)}")
        print(f"P@1: {round(avg_prec_at_one, 4)}")
        print(f"MAP: {round(avg_map, 4)}")
        return (total_correct[0]/total_examples, total_correct[1]/total_examples, total_correct[2]/total_examples), avg_mrr, avg_prec_at_one, avg_map