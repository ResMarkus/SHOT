import argparse
import os
import os.path as osp
import random

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from scipy.spatial.distance import cdist
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader
from torchvision import transforms

import loss
import network
from data_load import mnist, svhn, usps





def digit_load(args):
    train_bs = args.batch_size
    if args.dset == 's2m':
        train_source = svhn.SVHN('./data/svhn/', split='train', download=True,
                                 transform=transforms.Compose([
                                     transforms.Resize(32),
                                     transforms.ToTensor(),
                                     transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                 ]))
        test_source = svhn.SVHN('./data/svhn/', split='test', download=True,
                                transform=transforms.Compose([
                                    transforms.Resize(32),
                                    transforms.ToTensor(),
                                    transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                ]))
        train_target = mnist.MNIST_idx('./data/mnist/', train=True, download=True,
                                       transform=transforms.Compose([
                                           transforms.Resize(32),
                                           transforms.Lambda(lambda x: x.convert("RGB")),
                                           transforms.ToTensor(),
                                           transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                       ]))
        test_target = mnist.MNIST('./data/mnist/', train=False, download=True,
                                  transform=transforms.Compose([
                                      transforms.Resize(32),
                                      transforms.Lambda(lambda x: x.convert("RGB")),
                                      transforms.ToTensor(),
                                      transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                  ]))
    elif args.dset == 'u2m':
        train_source = usps.USPS('./data/usps/', train=True, download=True,
                                 transform=transforms.Compose([
                                     transforms.RandomCrop(28, padding=4),
                                     transforms.RandomRotation(10),
                                     transforms.ToTensor(),
                                     transforms.Normalize((0.5,), (0.5,))
                                 ]))
        test_source = usps.USPS('./data/usps/', train=False, download=True,
                                transform=transforms.Compose([
                                    transforms.RandomCrop(28, padding=4),
                                    transforms.RandomRotation(10),
                                    transforms.ToTensor(),
                                    transforms.Normalize((0.5,), (0.5,))
                                ]))
        train_target = mnist.MNIST_idx('./data/mnist/', train=True, download=True,
                                       transform=transforms.Compose([
                                           transforms.ToTensor(),
                                           transforms.Normalize((0.5,), (0.5,))
                                       ]))
        test_target = mnist.MNIST('./data/mnist/', train=False, download=True,
                                  transform=transforms.Compose([
                                      transforms.ToTensor(),
                                      transforms.Normalize((0.5,), (0.5,))
                                  ]))
    elif args.dset == 'm2u':
        train_source = mnist.MNIST('./data/mnist/', train=True, download=True,
                                   transform=transforms.Compose([
                                       transforms.ToTensor(),
                                       transforms.Normalize((0.5,), (0.5,))
                                   ]))
        test_source = mnist.MNIST('./data/mnist/', train=False, download=True,
                                  transform=transforms.Compose([
                                      transforms.ToTensor(),
                                      transforms.Normalize((0.5,), (0.5,))
                                  ]))

        train_target = usps.USPS_idx('./data/usps/', train=True, download=True,
                                     transform=transforms.Compose([
                                         transforms.ToTensor(),
                                         transforms.Normalize((0.5,), (0.5,))
                                     ]))
        test_target = usps.USPS('./data/usps/', train=False, download=True,
                                transform=transforms.Compose([
                                    transforms.ToTensor(),
                                    transforms.Normalize((0.5,), (0.5,))
                                ]))

    dset_loaders = {"source_tr": DataLoader(train_source, batch_size=train_bs, shuffle=True,
                                            num_workers=args.worker, drop_last=False),
                    "source_te": DataLoader(test_source, batch_size=train_bs * 2, shuffle=True,
                                            num_workers=args.worker, drop_last=False),
                    "target": DataLoader(train_target, batch_size=train_bs, shuffle=True,
                                         num_workers=args.worker, drop_last=False),
                    "target_idx": DataLoader(train_target, batch_size=train_bs, shuffle=False,
                                            num_workers=args.worker, drop_last=False),
                    "test": DataLoader(test_target, batch_size=train_bs * 2, shuffle=False,
                                       num_workers=args.worker, drop_last=False)}
    return dset_loaders


def cal_acc(loader, netF, netB, netC):
    with torch.no_grad():
        output_list=[]
        label_list=[]
        for inputs, labels in iter(loader):
            inputs = inputs.cuda()
            outputs = netC(netB(netF(inputs)))
            output_list.append(outputs.float().cpu())
            label_list.append(labels.float())

    all_output=torch.cat(output_list, dim=0)
    all_label=torch.cat(label_list, dim=0)
    _, all_pre = torch.max(all_output, 1)
    correct_num=torch.sum(all_pre.float() == all_label).item()
    all_num=all_label.size(0)
    accuracy = correct_num / float(all_num)
    mean_ent = torch.mean(loss.Entropy(nn.Softmax(dim=1)(all_output))).cpu().item()
    return accuracy * 100, mean_ent


def train_source(args):
    dset_loaders = digit_load(args)
    ## set base network
    if args.dset == 'u2m':
        netF = network.LeNetBase().cuda()
    elif args.dset == 'm2u':
        netF = network.LeNetBase().cuda()
    elif args.dset == 's2m':
        netF = network.DTNBase().cuda()

    netB = network.feat_bootleneck(type=args.classifier, feature_dim=netF.in_features,
                                   bottleneck_dim=args.bottleneck).cuda()
    netC = network.feat_classifier(type=args.layer, class_num=args.class_num,
                                   bottleneck_dim=args.bottleneck).cuda()


    param_groups = [{'params': netF.parameters(), 'lr': args.lr}] + \
                   [{'params': netB.parameters(), 'lr': args.lr}] + \
                   [{'params': netC.parameters(), 'lr': args.lr}]

    optimizer = optim.SGD(param_groups,lr=args.lr,weight_decay=1e-3,momentum=0.9,nesterov=True)

    acc_init = 0
    max_iter = args.max_epoch * len(dset_loaders["source_tr"])
    interval_iter = max_iter // 10
    iter_num = 0

    gamma = 10
    power = 0.75
    fun_decay = lambda i: (1 + gamma * i / max_iter) ** (-power)
    scheduler = LambdaLR(optimizer, lr_lambda=[fun_decay, fun_decay, fun_decay])

    netF.train()
    netB.train()
    netC.train()

    source_loader = dset_loaders["source_tr"]

    for epoch in range(args.max_epoch):
        for step, (inputs_source, labels_source) in enumerate(source_loader):

            if inputs_source.size(0) == 1:
                continue

            iter_num += 1


            # print("{:.8f}".format(scheduler.get_last_lr()[0]))
            inputs_source, labels_source = inputs_source.cuda(), labels_source.cuda()
            outputs_source = netC(netB(netF(inputs_source)))
            classifier_loss = loss.CrossEntropyLabelSmooth(num_classes=args.class_num, epsilon=args.smooth)(outputs_source,
                                                                                                            labels_source)
            optimizer.zero_grad()
            classifier_loss.backward()
            optimizer.step()

            scheduler.step()

            if iter_num % interval_iter == 0 or iter_num == max_iter:
                netF.eval()
                netB.eval()
                netC.eval()
                acc_s_tr, _ = cal_acc(dset_loaders['source_tr'], netF, netB, netC)
                acc_s_te, _ = cal_acc(dset_loaders['source_te'], netF, netB, netC)
                log_str = 'Task: {}, Iter:{}/{}; Accuracy = {:.2f}%/ {:.2f}%'.format(args.dset, iter_num, max_iter,
                                                                                     acc_s_tr, acc_s_te)
                args.out_file.write(log_str + '\n')
                args.out_file.flush()
                print(log_str + '\n')

                if acc_s_te >= acc_init:
                    acc_init = acc_s_te
                    best_netF = netF.state_dict()
                    best_netB = netB.state_dict()
                    best_netC = netC.state_dict()

                netF.train()
                netB.train()
                netC.train()

    torch.save(best_netF, osp.join(args.output_dir, "source_F.pt"))
    torch.save(best_netB, osp.join(args.output_dir, "source_B.pt"))
    torch.save(best_netC, osp.join(args.output_dir, "source_C.pt"))

    return netF, netB, netC


def test_target(args):
    dset_loaders = digit_load(args)
    ## set base network
    if args.dset == 'u2m':
        netF = network.LeNetBase().cuda()
    elif args.dset == 'm2u':
        netF = network.LeNetBase().cuda()
    elif args.dset == 's2m':
        netF = network.DTNBase().cuda()

    netB = network.feat_bootleneck(type=args.classifier, feature_dim=netF.in_features,
                                   bottleneck_dim=args.bottleneck).cuda()
    netC = network.feat_classifier(type=args.layer, class_num=args.class_num, bottleneck_dim=args.bottleneck).cuda()

    args.modelpath = args.output_dir + '/source_F.pt'
    netF.load_state_dict(torch.load(args.modelpath))
    args.modelpath = args.output_dir + '/source_B.pt'
    netB.load_state_dict(torch.load(args.modelpath))
    args.modelpath = args.output_dir + '/source_C.pt'
    netC.load_state_dict(torch.load(args.modelpath))
    netF.eval()
    netB.eval()
    netC.eval()

    acc, _ = cal_acc(dset_loaders['test'], netF, netB, netC)
    log_str = 'Task: {}, Accuracy = {:.2f}%'.format(args.dset, acc)
    args.out_file.write(log_str + '\n')
    args.out_file.flush()
    print(log_str + '\n')


def print_args(args):
    s = "==========================================\n"
    for arg, content in args.__dict__.items():
        s += "{}:{}\n".format(arg, content)
    return s


def train_target(args):
    dset_loaders = digit_load(args)
    ## set base network
    if args.dset == 'u2m':
        netF = network.LeNetBase().cuda()
    elif args.dset == 'm2u':
        netF = network.LeNetBase().cuda()
    elif args.dset == 's2m':
        netF = network.DTNBase().cuda()

    netB = network.feat_bootleneck(type=args.classifier, feature_dim=netF.in_features,
                                   bottleneck_dim=args.bottleneck).cuda()
    netC = network.feat_classifier(type=args.layer, class_num=args.class_num, bottleneck_dim=args.bottleneck).cuda()

    args.modelpath = args.output_dir + '/source_F.pt'
    netF.load_state_dict(torch.load(args.modelpath))
    args.modelpath = args.output_dir + '/source_B.pt'
    netB.load_state_dict(torch.load(args.modelpath))
    args.modelpath = args.output_dir + '/source_C.pt'
    netC.load_state_dict(torch.load(args.modelpath))
    netC.eval()

    for param in netC.parameters():
        param.requires_grad = False

    param_groups = [{'params': netF.parameters(), 'lr': args.lr}] + \
                   [{'params': netB.parameters(), 'lr': args.lr}] + \
                   [{'params': netC.parameters(), 'lr': args.lr}]

    optimizer = optim.SGD(param_groups,lr=args.lr,weight_decay=1e-3,momentum=0.9,nesterov=True)

    target_loader=dset_loaders["target"]
    max_iter = args.max_epoch * len(target_loader)
    interval_iter = len(target_loader)
    # interval_iter = max_iter // args.interval
    iter_num = 0

    gamma = 10
    power = 0.75
    fun_decay = lambda i: (1 + gamma * i / max_iter) ** (-power)
    scheduler = LambdaLR(optimizer, lr_lambda=[fun_decay, fun_decay, fun_decay])

    for epoch in range(args.max_epoch):
        for step, (inputs_test, _, tar_idx) in enumerate(target_loader):
            optimizer.zero_grad()

            if inputs_test.size(0) == 1:
                continue

            if iter_num % interval_iter == 0 and args.cls_par > 0:
                netF.eval()
                netB.eval()
                mem_label = obtain_label(dset_loaders['target_idx'], netF, netB, netC, args)
                mem_label = torch.from_numpy(mem_label).cuda()
                netF.train()
                netB.train()

            iter_num += 1

            inputs_test = inputs_test.cuda()
            features_test = netB(netF(inputs_test))
            outputs_test = netC(features_test)

            if args.cls_par > 0:
                pred = mem_label[tar_idx]
                classifier_loss = args.cls_par * nn.CrossEntropyLoss()(outputs_test, pred)
            else:
                classifier_loss = torch.tensor(0.0).cuda()

            if args.ent:
                softmax_out = nn.Softmax(dim=1)(outputs_test)
                entropy_loss = torch.mean(loss.Entropy(softmax_out))
                if args.gent:
                    msoftmax = softmax_out.mean(dim=0)
                    entropy_loss -= torch.sum(-msoftmax * torch.log(msoftmax + 1e-5))

                im_loss = entropy_loss * args.ent_par
                classifier_loss += im_loss



            optimizer.zero_grad()
            classifier_loss.backward()
            optimizer.step()

            scheduler.step()

            if iter_num % interval_iter == 0 or iter_num == max_iter:
                netF.eval()
                netB.eval()
                acc, _ = cal_acc(dset_loaders['test'], netF, netB, netC)
                log_str = 'Task: {}, Iter:{}/{}; Accuracy = {:.2f}%'.format(args.dset, iter_num, max_iter, acc)
                args.out_file.write(log_str + '\n')
                args.out_file.flush()
                print(log_str + '\n')
                netF.train()
                netB.train()

    if args.issave:
        torch.save(netF.state_dict(), osp.join(args.output_dir, "target_F_" + args.savename + ".pt"))
        torch.save(netB.state_dict(), osp.join(args.output_dir, "target_B_" + args.savename + ".pt"))
        torch.save(netC.state_dict(), osp.join(args.output_dir, "target_C_" + args.savename + ".pt"))

    return netF, netB, netC


def obtain_label(loader, netF, netB, netC, args):
    start_test = True
    with torch.no_grad():
        for inputs, labels in iter(loader):

            inputs = inputs.cuda()
            feas = netB(netF(inputs))
            outputs = netC(feas)
            if start_test:
                all_fea = feas.float().cpu()
                all_output = outputs.float().cpu()
                all_label = labels.float()
                start_test = False
            else:
                all_fea = torch.cat((all_fea, feas.float().cpu()), 0)
                all_output = torch.cat((all_output, outputs.float().cpu()), 0)
                all_label = torch.cat((all_label, labels.float()), 0)
    all_output = nn.Softmax(dim=1)(all_output)
    _, predict = torch.max(all_output, 1)
    accuracy = torch.sum(torch.squeeze(predict).float() == all_label).item() / float(all_label.size()[0])

    all_fea = torch.cat((all_fea, torch.ones(all_fea.size(0), 1)), 1)
    all_fea = (all_fea.t() / torch.norm(all_fea, p=2, dim=1)).t()
    all_fea = all_fea.float().cpu().numpy()

    K = all_output.size(1)
    aff = all_output.float().cpu().numpy()
    initc = aff.transpose().dot(all_fea)
    initc = initc / (1e-8 + aff.sum(axis=0)[:, None])
    dd = cdist(all_fea, initc, 'cosine')
    pred_label = dd.argmin(axis=1)
    acc = np.sum(pred_label == all_label.float().numpy()) / len(all_fea)

    for round in range(1):
        aff = np.eye(K)[pred_label]
        initc = aff.transpose().dot(all_fea)
        initc = initc / (1e-8 + aff.sum(axis=0)[:, None])
        dd = cdist(all_fea, initc, 'cosine')
        pred_label = dd.argmin(axis=1)
        acc = np.sum(pred_label == all_label.float().numpy()) / len(all_fea)

    log_str = 'Accuracy = {:.2f}% -> {:.2f}%'.format(accuracy * 100, acc * 100)
    args.out_file.write(log_str + '\n')
    args.out_file.flush()
    print(log_str + '\n')
    return pred_label.astype('int')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='SHOT')
    parser.add_argument('--gpu_id', type=str, nargs='?', default='0', help="device id to run")
    parser.add_argument('--s', type=int, default=0, help="source")
    parser.add_argument('--t', type=int, default=1, help="target")
    parser.add_argument('--max_epoch', type=int, default=30, help="maximum epoch")
    parser.add_argument('--batch_size', type=int, default=64, help="batch_size")
    parser.add_argument('--worker', type=int, default=4, help="number of workers")
    parser.add_argument('--dset', type=str, default='s2m', choices=['u2m', 'm2u', 's2m'])
    parser.add_argument('--lr', type=float, default=0.01, help="learning rate")
    parser.add_argument('--seed', type=int, default=2020, help="random seed")
    parser.add_argument('--cls_par', type=float, default=0.3)
    parser.add_argument('--ent_par', type=float, default=1.0)
    parser.add_argument('--gent', type=bool, default=True)
    parser.add_argument('--ent', type=bool, default=True)
    parser.add_argument('--bottleneck', type=int, default=256)
    parser.add_argument('--layer', type=str, default="wn", choices=["linear", "wn"])
    parser.add_argument('--classifier', type=str, default="bn", choices=["ori", "bn"])
    parser.add_argument('--smooth', type=float, default=0.1)
    parser.add_argument('--output', type=str, default='')
    parser.add_argument('--issave', type=bool, default=True)
    args = parser.parse_args()
    args.class_num = 10

    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_id
    SEED = args.seed
    torch.manual_seed(SEED)
    torch.cuda.manual_seed(SEED)
    np.random.seed(SEED)
    random.seed(SEED)
    # torch.backends.cudnn.deterministic = True

    args.output_dir = osp.join(args.output, 'seed' + str(args.seed), args.dset)
    if not osp.exists(args.output_dir):
        os.system('mkdir -p ' + args.output_dir)
    if not osp.exists(args.output_dir):
        os.mkdir(args.output_dir)

    if not osp.exists(osp.join(args.output_dir + '/source_F.pt')):
        args.out_file = open(osp.join(args.output_dir, 'log_src.txt'), 'w')
        args.out_file.write(print_args(args) + '\n')
        args.out_file.flush()
        train_source(args)
        test_target(args)

    args.savename = 'par_' + str(args.cls_par)
    args.out_file = open(osp.join(args.output_dir, 'log_tar_' + args.savename + '.txt'), 'w')
    args.out_file.write(print_args(args) + '\n')
    args.out_file.flush()
    train_target(args)
