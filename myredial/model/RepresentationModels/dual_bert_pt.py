from model.utils import *

class BERTDualPTEncoder(nn.Module):

    '''dual bert and dual latent interaction: one-to-many mechanism'''
    
    def __init__(self, **args):
        super(BERTDualPTEncoder, self).__init__()
        model = args['pretrained_model']
        s = args['smoothing']

        self.ctx_encoder = BertFullEmbedding(model=model)
        self.can_encoder = BertFullEmbedding(model=model)
        self.criterion = nn.CrossEntropyLoss(ignore_index=-1)
        self.vocab_size = self.ctx_encoder.model.config.vocab_size
        self.hidden_size = self.ctx_encoder.model.config.hidden_size
        self.lm_head = nn.Linear(self.hidden_size, self.vocab_size)

    def _encode(self, cid, rid, cid_mask, rid_mask):
        cid_rep = self.ctx_encoder(cid, cid_mask)
        rid_rep = self.can_encoder(rid, rid_mask)
        cid_lm, rid_lm = self.lm_head(cid_rep), self.lm_head(rid_rep)
        return cid_rep[:, 0, :], rid_rep[:, 0, :], cid_lm, rid_lm

    @torch.no_grad()
    def get_cand(self, ids, attn_mask):
        rid_rep = self.can_encoder(ids, attn_mask)
        return rid_rep

    @torch.no_grad()
    def get_ctx(self, ids, attn_mask):
        cid_rep = self.ctx_encoder(ids, attn_mask)
        return cid_rep

    @torch.no_grad()
    def predict(self, batch):
        cid = batch['ids']
        cid_mask = torch.ones_like(cid)
        rid = batch['rids']
        rid_mask = batch['rids_mask']

        batch_size = rid.shape[0]
        cid_rep, rid_rep = self._encode(cid, rid, cid_mask, rid_mask)
        dot_product = torch.matmul(cid_rep, rid_rep.t()).squeeze(0)
        dot_product /= np.sqrt(768)     # scale dot product
        return dot_product
    
    def forward(self, batch):
        cid = batch['ids']
        rid = batch['rids']
        cid_mask = batch['ids_mask']
        rid_mask = batch['rids_mask']
        cid_mask_label = batch['ids_mask_label']    # [B, S]
        rid_mask_label = batch['rids_mask_label']

        inner_bsz = int(len(cid)/2)
        cid_rep, rid_rep, cid_lm, rid_lm = self._encode(cid, rid, cid_mask, rid_mask)

        # mlm loss
        cids_mlm_loss = self.criterion(
            cid_lm.view(-1, self.vocab_size),
            cid_mask_label.view(-1)
        )
        rids_mlm_loss = self.criterion(
            rid_lm.view(-1, self.vocab_size),
            rid_mask_label.view(-1)
        )
        mlm_loss = cids_mlm_loss + rids_mlm_loss

        # mlm acc
        token_acc_num = (F.softmax(cid_lm, dim=-1).max(dim=-1)[1] == cid_mask_label).sum()
        token_acc_num += (F.softmax(rid_lm, dim=-1).max(dim=-1)[1] == rid_mask_label).sum()
        size = 2 * len(cid_mask_label.view(-1))
        token_acc = token_acc_num / size

        # constrastive loss
        cid_rep_1, cid_rep_2 = torch.split(cid_rep, inner_bsz)
        rid_rep_1, rid_rep_2 = torch.split(rid_rep, inner_bsz)
        assert len(cid_rep_1) == len(cid_rep_2)
        assert len(rid_rep_1) == len(rid_rep_2)

        # c-r
        dot_product1 = torch.matmul(cid_rep_1, rid_rep_1.t())     # [B, B]
        dot_product1 /= np.sqrt(768)     # scale dot product
        dot_product2 = torch.matmul(cid_rep_1, rid_rep_2.t())     # [B, B]
        dot_product2 /= np.sqrt(768)     # scale dot product
        dot_product3 = torch.matmul(cid_rep_2, rid_rep_1.t())     # [B, B]
        dot_product3 /= np.sqrt(768)     # scale dot product
        dot_product4 = torch.matmul(cid_rep_2, rid_rep_2.t())     # [B, B]
        dot_product4 /= np.sqrt(768)     # scale dot product
        # c-c
        dot_product5 = torch.matmul(cid_rep_1, cid_rep_2.t())     # [B, B]
        dot_product5 /= np.sqrt(768)     # scale dot product
        # r-r
        dot_product6 = torch.matmul(rid_rep_1, rid_rep_2.t())     # [B, B]
        dot_product6 /= np.sqrt(768)     # scale dot product

        # constrastive loss
        mask = torch.zeros_like(dot_product1)
        mask[range(inner_bsz), range(inner_bsz)] = 1. 
        cl_loss = 0
        loss_ = F.log_softmax(dot_product1, dim=-1) * mask
        cl_loss += (-loss_.sum(dim=1)).mean()
        loss_ = F.log_softmax(dot_product2, dim=-1) * mask
        cl_loss += (-loss_.sum(dim=1)).mean()
        loss_ = F.log_softmax(dot_product3, dim=-1) * mask
        cl_loss += (-loss_.sum(dim=1)).mean()
        loss_ = F.log_softmax(dot_product4, dim=-1) * mask
        cl_loss += (-loss_.sum(dim=1)).mean()
        loss_ = F.log_softmax(dot_product5, dim=-1) * mask
        cl_loss += (-loss_.sum(dim=1)).mean()
        loss_ = F.log_softmax(dot_product6, dim=-1) * mask
        cl_loss += (-loss_.sum(dim=1)).mean()

        # acc
        acc_num = (F.softmax(dot_product1, dim=-1).max(dim=-1)[1] == torch.LongTensor(torch.arange(inner_bsz)).cuda()).sum().item()
        acc = acc_num/inner_bsz

        return mlm_loss, cl_loss, token_acc, acc
