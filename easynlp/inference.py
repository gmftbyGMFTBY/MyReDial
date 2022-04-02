from header import *
from dataloader import *
from model import *
from config import *
from inference_utils import *

def parser_args():
    parser = argparse.ArgumentParser(description='train parameters')
    parser.add_argument('--dataset', default='ecommerce', type=str)
    parser.add_argument('--model', type=str)
    parser.add_argument('--local_rank', type=int)
    parser.add_argument('--nums', type=int)
    parser.add_argument('--gen_dataset_num', type=int, default=500000)
    parser.add_argument('--gen_dataset_ctx_length', type=int, default=5)
    parser.add_argument('--gen_dataset_topk', type=int, default=5)
    parser.add_argument('--gray_topk', type=int, default=5)
    parser.add_argument('--gray_start', type=int, default=372)
    parser.add_argument('--cut_size', type=int, default=500000)
    parser.add_argument('--work_mode', type=str, default='response')
    parser.add_argument('--pool_size', type=int, default=200)
    parser.add_argument('--data_filter_size', type=int, default=500000)
    return parser.parse_args()


def inference(**args):
    work_mode = args['work_mode']
    data, data_iter, sampler = load_dataset(args)
    sampler.set_epoch(0)

    random.seed(args['seed'])
    torch.manual_seed(args['seed'])
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args['seed'])

    agent = load_model(args)
    pretrained_model_name = args['pretrained_model'].replace('/', '_')

    if work_mode in ['writer-inference']:
        # load the pre-trained model on writer dataset
        agent.load_model(f'{args["root_dir"]}/ckpt/writer/{args["model"]}/best_{pretrained_model_name}.pt')
    else:
        agent.load_model(f'{args["root_dir"]}/ckpt/{args["dataset"]}/{args["model"]}/best_{pretrained_model_name}_{args["version"]}.pt')

    if work_mode in ['response', 'simcse-response']:
        agent.inference(data_iter, size=args['cut_size'])
        pass
    elif work_mode in ['generate']:
        agent.batch_generation_inference(data_iter)
    elif work_mode in ['phrase-generate']:
        agent.build_offline_index(data_iter)
    elif work_mode in ['data-filter']:
        agent.inference_data_filter(data_iter, size=args['cut_size'])
    elif work_mode in ['bert-aug']:
        agent.inference(data_iter, size=args['cut_size'])
    elif work_mode in ['wz-simcse']:
        agent.inference_wz_simcse(data_iter, size=args['cut_size'])
        pass
    elif work_mode in ['simcse-ctx']:
        agent.inference_simcse_ctx(data_iter, size=args['cut_size'])
    elif work_mode in ['simcse-ctx-unlikelyhood']:
        agent.inference_simcse_unlikelyhood_ctx(data_iter, size=args['cut_size'])
    elif work_mode in ['response-with-src']:
        agent.inference_with_source(data_iter, size=args['cut_size'])
    elif work_mode in ['full-ctx-res']:
        agent.inference_full_ctx_res(data_iter, size=args['cut_size'])
        pass
    elif work_mode in ['writer-inference']:
        agent.inference_writer(data_iter, size=args['cut_size'])
    # elif work_mode in ['context', 'gray-one2many', 'gray', 'unparallel']:
    elif work_mode in ['context']:
        # gray and gray-one2many will use the checkpoint generated by the context work_mode
        agent.inference_context(data_iter, size=args['cut_size'])
    elif work_mode in ['context-test']:
        # gray and gray-one2many will use the checkpoint generated by the context work_mode
        agent.inference_context_test(data_iter, size=args['cut_size'])
    else:
        pass
    return agent

if __name__ == "__main__":
    args = vars(parser_args())
    bert_fp_args = deepcopy(args)
    args['mode'] = 'inference'
    config = load_config(args)
    args.update(config)
    
    torch.cuda.set_device(args['local_rank'])
    torch.distributed.init_process_group(backend='nccl', init_method='env://')

    agent = inference(**args)

    # barries
    torch.distributed.barrier()

    if args['local_rank'] != 0:
        if args['work_mode'] in ['self-play', 'gray-simcse-unlikelyhood', 'gray-one2many', 'generate', 'gray-hard', 'gray-simcse']:
            pass
        else:
            exit()

    # only the main process will run the following inference strategies
    if args['work_mode'] in ['writer-inference']:
        writer_with_source_strategy(args)
    elif args['work_mode'] in ['inference-time-cost']:
        inference_time_cost_strategy(args, agent)
    elif args['work_mode'] in ['data-filter']:
        data_filter_strategy(args)
    elif args['work_mode'] in ['gray-test']:
        gray_test_strategy(args)
    elif args['work_mode'] in ['bert-aug']:
        da_strategy(args)
    elif args['work_mode'] in ['response', 'wz-simcse']:
        response_strategy(args)
    elif args['work_mode'] in ['simcse-response']:
        simcse_response_strategy(args)
    elif args['work_mode'] in ['response-test']:
        response_test_strategy(args)
    elif args['work_mode'] in ['response-with-src']:
        response_with_source_strategy(args)
    elif args['work_mode'] in ['full-ctx-res']:
        context_response_strategy(args)
    elif args['work_mode'] in ['gray']:
        gray_strategy(args)
    elif args['work_mode'] in ['gray-one2many']:
        gray_one2many_strategy(args)
    elif args['work_mode'] in ['gray-simcse']:
        gray_simcse_strategy(args)
        torch.distributed.barrier()
        # combination
        combine_all_generate_samples_pt(args)
    elif args['work_mode'] in ['gray-simcse-unlikelyhood']:
        # only one process to run
        gray_simcse_unlikelyhood_strategy(args)
    elif args['work_mode'] in ['gray-one2many-with-src']:
        gray_one2many_with_source_strategy(args)
    elif args['work_mode'] in ['gray-hard']:
        gray_hard_strategy(args)
    elif args['work_mode'] in ['gray-hard-test']:
        gray_hard_test_strategy(args)
    elif args['work_mode'] == 'context':
        pass
    elif args['work_mode'] == 'res-search-ctx':
        res_search_ctx_strategy(args)
    elif args['work_mode'] == 'unparallel':
        # response_strategy(args)
        print(f'[!] build index for responses over')
        unparallel_strategy(args)
    # elif args['work_mode'] in ['self-play', 'gray-extend']:
    elif args['work_mode'] in ['self-play', 'gray-extend']:
        gray_extend_strategy(args)
        # self_play_strategy(args)
        torch.distributed.barrier()
        combine_all_generate_samples(args)
    else:
        # raise Exception(f'[!] Unknown work mode: {args["work_mode"]}')
        pass

