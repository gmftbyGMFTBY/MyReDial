from model.utils import *

class PostTrainAgent(RetrievalBaseAgent):

    def __init__(self, vocab, model, args):
        super(PostTrainAgent, self).__init__()
        self.args = args
        self.vocab, self.model = vocab, model
        if args['mode'] == 'train':
            self.set_test_interval()
            self.load_checkpoint()
        else:
            # open the test save scores file handler
            pretrained_model_name = self.args['pretrained_model'].replace('/', '_')
            path = f'{self.args["root_dir"]}/rest/{self.args["dataset"]}/{self.args["model"]}/scores_log_{pretrained_model_name}.txt'
            self.log_save_file = open(path, 'w')
        if torch.cuda.is_available():
            self.model.cuda()
        if args['mode'] in ['train', 'inference']:
            self.set_optimizer_scheduler_ddp()
        self.criterion = nn.BCEWithLogitsLoss()
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
            self.optimizer.zero_grad()
            with autocast():
                output = self.model(batch)    # [B]
                label = batch['label']
                loss = self.criterion(output, label.to(torch.float))
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
            
            output = torch.sigmoid(output) > 0.5
            now_correct = torch.sum(output == label).item()
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
    def test_model(self, test_iter, print_output=False):
        self.model.eval()
        pbar = tqdm(test_iter)
        total_mrr, total_prec_at_one, total_map = 0, 0, 0
        total_examples, total_correct = 0, 0
        k_list = [1, 2, 5, 10]
        for idx, batch in enumerate(pbar):
            label = batch['label']
            scores = torch.sigmoid(self.model(batch)).cpu().tolist()
            
            # print output
            if print_output:
                for ids, score in zip(batch['ids'], scores):
                    text = self.convert_to_text(ids)
                    score = round(score, 4)
                    self.log_save_file.write(f'[Score {score}] {text}\n')
                self.log_save_file.write('\n')
            
            rank_by_pred, pos_index, stack_scores = \
          calculate_candidates_ranking(
                np.array(scores), 
                np.array(label.cpu().tolist()),
                10)
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
        return {
            f'R10@{k_list[0]}': round(((total_correct[0]/total_examples)*100), 2),        
            f'R10@{k_list[1]}': round(((total_correct[1]/total_examples)*100), 2),        
            f'R10@{k_list[2]}': round(((total_correct[2]/total_examples)*100), 2),        
            'MRR': round(avg_mrr, 4),
            'P@1': round(avg_prec_at_one, 4),
            'MAP': round(avg_map, 4),
        }