from inference import *
from header import *
from .utils import *

def phrases_strategy(args):
    embds, texts = [], []
    already_added = []
    current_num = 0
    for i in tqdm(range(args['nums'])):
        for idx in range(100):
            try:
                embd, text = torch.load(
                    f'{args["root_dir"]}/data/{args["dataset"]}/inference_{args["model"]}_{i}_{idx}.pt'
                )
                print(f'[!] load {args["root_dir"]}/data/{args["dataset"]}/inference_{args["model"]}_{i}_{idx}.pt')
                current_num += len(embd)
            except:
                break
            embds.append(embd)
            texts.extend(text)
            already_added.append((i, idx))
            print(f'[!] collect embeddings: {current_num}')
            if current_num > args['train_size']:
                break
        if current_num > args['train_size']:
            break
    embds = np.concatenate(embds) 
    searcher = Searcher(args['index_type'], dimension=args['dimension'])
    searcher._build(embds, texts, speedup=True)
    # searcher._build(embds, texts, speedup=False)
    print(f'[!] train the searcher over')
    # big index (over 10M), just training with GPU, other operations on CPU
    # https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index
    searcher.move_to_cpu()

    # add the external dataset
    for i in tqdm(range(args['nums'])):
        for idx in range(100):
            if (i, idx) in already_added:
                continue
            try:
                embd, text = torch.load(
                    f'{args["root_dir"]}/data/{args["dataset"]}/inference_{args["model"]}_{i}_{idx}.pt'
                )
                print(f'[!] load {args["root_dir"]}/data/{args["dataset"]}/inference_{i}_{idx}.pt')
                current_num += len(embd)
            except:
                break
            searcher.add(embd, text)
            if current_num > args['overall_size'] :
                break
        if current_num > args['overall_size']:
            break
    print(f'[!] total samples: {searcher.searcher.ntotal}')

    model_name = args['model']
    pretrained_model_name = args['pretrained_model'].replace('/', '_')
    searcher.save(
        f'{args["root_dir"]}/data/{args["dataset"]}/{model_name}_{pretrained_model_name}_faiss.ckpt',
        f'{args["root_dir"]}/data/{args["dataset"]}/{model_name}_{pretrained_model_name}_corpus.ckpt',
    )
    print(f'[!] save faiss index over')