   
from pymongo import MongoClient
from urllib.parse import urlparse
from tqdm import tqdm
from datetime import datetime, timedelta
import random
import os
import fasttext
from sklearn.metrics import classification_report, roc_auc_score, recall_score, f1_score, precision_score,confusion_matrix,accuracy_score
from sklearn.model_selection import train_test_split
from common import *
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
import joblib
import argparse
import requests
import subprocess
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import json
from torch.utils.data import Dataset, DataLoader
import numpy as np
from model_inference import IsTypo
import faiss
import redis
import os
from torch.utils.data import DataLoader, random_split
from common import BAGGING_MODEL_NUM
import pickle
import pandas as pd
import shutil
os.environ["CUDA_VISIBLE_DEVICES"] = "1"


class CharCNN(nn.Module):
    def __init__(self, args):
        super(CharCNN, self).__init__()
        
        self.conv1 = nn.Sequential(
            nn.Conv1d(args.num_features, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            #nn.MaxPool1d(kernel_size=2, stride=2)
        )
        
        self.conv2 = nn.Sequential(
            nn.Conv1d(128, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            #nn.MaxPool1d(kernel_size=2, stride=2)
        )
        
        self.conv3 = nn.Sequential(
            nn.Conv1d(128, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU()
        )
        
        self.conv4 = nn.Sequential(
            nn.Conv1d(128, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU()
        )
        
        self.adaptive_pool = nn.AdaptiveMaxPool1d(8) 
        

        self.fc1 = nn.Sequential(
            nn.Linear(128 * 8, 128),
            nn.ReLU(),
            nn.Dropout(p=args.dropout)
        )
        
        self.fc2 = nn.Sequential(
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Dropout(p=args.dropout)
        )
        
        self.fc3 = nn.Linear(128, 1)
    
    def forward(self, x):
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = self.conv4(x)
        
        x = self.adaptive_pool(x)
        x = x.view(x.size(0), -1)
        
        x = self.fc1(x)
        x = self.fc2(x)
        x = self.fc3(x)
        
        return x




class FocalLoss(nn.Module):
    def __init__(self, alpha=0.5, gamma=2.0, reduction='mean'):
        super(FocalLoss, self).__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.reduction = reduction

    def forward(self, inputs, targets):
        BCE_loss = F.binary_cross_entropy_with_logits(inputs, targets, reduction='none')
        pt = torch.exp(-BCE_loss)
        F_loss = self.alpha * (1-pt)**self.gamma * BCE_loss
        
        if self.reduction == 'mean':
            return F_loss.mean()
        elif self.reduction == 'sum':
            return F_loss.sum()
        else:
            return F_loss





class DomainDataset(Dataset):
    def __init__(self, phish_domains, benign_domains, max_len=64):
        with open("./alphabet.json", "r", encoding="utf-8") as f:
            vocab_list = json.load(f)
        self.max_len = max_len
        self.chars = [c for c in vocab_list]
        self.char2idx = {c: i + 1 for i, c in enumerate(self.chars)}

        self.domains = []
        self.labels = []


        for d in phish_domains:
            self.domains.append(d.lower())
            self.labels.append(1)

   
        for d in benign_domains:
            self.domains.append(d.lower())
            self.labels.append(0)

    def encode_domain(self, domain):
        x = np.zeros((len(self.chars) + 1, self.max_len), dtype=np.float32)
        for i, c in enumerate(domain[:self.max_len]):
            if c in self.char2idx:
                x[self.char2idx[c], i] = 1.0
        return x

    def __len__(self):
        return len(self.domains)

    def __getitem__(self, idx):
        x = self.encode_domain(self.domains[idx])
        y = self.labels[idx]
        return torch.tensor(x, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)


def auto_params(num_vectors, d):
    nlist = int(np.power(num_vectors, 0.5))

    nlist = 1 << (nlist - 1).bit_length()

  
    M = max(1, d // 32)
    while d % M != 0:
        M -= 1

    nbits = 8 

    return nlist, M, nbits


class FaissIVFFlatIndex:
    def __init__(self, num_vectors, d, gpu_id=0):
    
        self.d = d
        self.gpu_id = gpu_id

        self.nlist, self.M, self.nbits = auto_params(num_vectors, d)

        quantizer = faiss.IndexFlatIP(d)
        index_cpu = faiss.IndexIVFFlat(quantizer, d, self.nlist, faiss.METRIC_INNER_PRODUCT)
        self.res = faiss.StandardGpuResources()
        self.index = faiss.index_cpu_to_gpu(self.res, gpu_id, index_cpu)
        self.index.nprobe = 32






client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]




def save_fasttext_format(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        for domain, label in data:
            f.write(f"__label__{label} {domain}\n")


def get_data_from_db(exp_name, start_time=None):
    collection = db[exp_name]
    
    query = {}
    if start_time is not None:
        query["timestamp"] = {"$gte": start_time, "$lt": datetime.now()}


    cursor = collection.find(query, {"_id": 0, "ori_domain": 1, "phish_category": 1, "domain_classifier": 1})


    tp, fn, tn, fp = [], [], [], []

    for doc in cursor:
        phish = doc.get("phish_category")
        classifier = doc.get("domain_classifier")
        domain = doc.get("ori_domain")
       
        
        if phish == 2 and classifier == 1:
            tp.append(domain)
        elif phish == 2 and classifier == 0:
            fn.append(domain)
        elif phish != 2 and classifier == 0:
            tn.append(domain)
        elif phish != 2 and classifier == 1:
            fp.append(domain)

    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp}



def get_from_all_data(query,exp_name):
    collection = db["all_data_"+exp_name]
    results = collection.find(query, {"_id": 0, "ori_domain": 1})
    return {doc["ori_domain"] for doc in results if "ori_domain" in doc}
    
    


def get_warmup_domains():
    """Warmup seed domains (known phishing), merged into the phish side on every retrain"""
    with open(WARMUP_DIR, 'rb') as f:
        return set(pickle.load(f))


def get_benign_from_redis(benign_needed):
    """Negative samples: randomly sampled from the certstream dedup cache (Redis db0)"""
    redis_cache = redis.Redis(host='localhost', port=REDIS_DEDUP_PORT, db=0)
    result = set()

    while len(result) < benign_needed:
        k = redis_cache.randomkey()
        if k:
            result.add(k)
    return [r.decode('utf-8').replace("domain:", "") for r in result]


def get_training_data(exp_name, start_time=None, neg_sampling="redis"):

    past_db_data = get_data_from_db(exp_name)
    tp = set(past_db_data["tp"])
    fp = set(past_db_data["fp"])
    tn = set(past_db_data["tn"])
    fn = set(past_db_data["fn"])


    phish_domain = tp | fn
    phish_domain |= get_warmup_domains()
    
    benign_needed = len(phish_domain)*BAGGING_MODEL_NUM

    if neg_sampling == "redis":
        benign_domain = get_benign_from_redis(benign_needed)
    else:
        benign_domain = get_fixed_benign_domains()
        benign_domain = random.sample(benign_domain, min(len(benign_domain), benign_needed))

    print(f'neg sampling:{neg_sampling},phish size:{len(phish_domain)},benign size:{len(benign_domain)}')
    return transform_domains_unique(phish_domain),transform_domains_unique(benign_domain)
    
    
def get_fixed_benign_domains():
    """Negative samples all come from the Tranco top-1m list"""
    df = pd.read_csv(TRANCO_DIR, header=None, names=['id', 'domain'])
    fixed_benign_domains_list = df["domain"].tolist()
    fixed_benign_domains_list = transform_domains_unique(fixed_benign_domains_list)
    return fixed_benign_domains_list
    
    

    
    

def train_tfidf_logisticregression_model(exp_name,phish_domain,benign_domain,index):
    x = list(phish_domain) + list(benign_domain)
    y = [1] * len(phish_domain) + [0] * len(benign_domain) 
    pipeline = Pipeline([
    ('tfidf', TfidfVectorizer(analyzer='char', ngram_range=(2,4), lowercase=True,max_features=10000)),
    ('classifier', LogisticRegression(solver='liblinear'))])
    pipeline.fit(x,y)
    joblib.dump(pipeline,f'../models/ablation/{exp_name}/models/tfidf_logisticregression_{index}.sav')
    return len(phish_domain),len(benign_domain)


def train_tfidf_logisticregression_bagging_model(exp_name,phish_domain,benign_domain):
    benign_domain = list(benign_domain)
    random.shuffle(benign_domain)
    chunk_size = len(benign_domain) // BAGGING_MODEL_NUM
    
    for i in range(BAGGING_MODEL_NUM):
        print(f"Training model{i}")
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < BAGGING_MODEL_NUM - 1 else len(benign_domain)
        benign_part = benign_domain[start:end]
       
        a,b = train_tfidf_logisticregression_model(exp_name,phish_domain,benign_part,i)
        print(f'TFIDF{i}:phish:{a},benign:{b}')


    return len(phish_domain),len(benign_domain)




def train_fasttext_bagging_model(exp_name,phish_domain,benign_domain):

    benign_domain = list(benign_domain)
    random.shuffle(benign_domain)
    chunk_size = len(benign_domain) // BAGGING_MODEL_NUM
    
    for i in range(BAGGING_MODEL_NUM):
        print(f"Training model{i}")
    
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < BAGGING_MODEL_NUM - 1 else len(benign_domain)
        benign_part = benign_domain[start:end]
        a,b = train_fasttext_single_model(exp_name,phish_domain,benign_part,i)
        print(f'Fasttext{i}:phish:{a},benign:{b}')
        
        
    return len(phish_domain),len(benign_domain)
    


def train_fasttext_single_model(exp_name,phish_domain,benign_domain,index):
    train_set = [(d, 1) for d in phish_domain] + [(d, 0) for d in benign_domain]
    train_file = f"../models/ablation/{exp_name}/data/train_bag_{index}.txt"
    save_fasttext_format(train_set, train_file)
    epoch = 50
    lr = 0.5
    model = fasttext.train_supervised(
            input=train_file,
            lr=lr,
            epoch=epoch,
            dim=10,
            loss='softmax',
            minn=2,
            maxn=6,
            verbose=0,

        )
    model.save_model(f"../models/ablation/{exp_name}/models/best_model_{index}.ftz")
    return len(phish_domain),len(benign_domain)
    




def train_charcnn_model(exp_name, phish_domain, benign_domain,index=None):
    with open("./alphabet.json", "r", encoding="utf-8") as f:
        vocab_list = json.load(f)

    class Args:
        num_features = len(vocab_list) + 1 
        dropout = 0.5

    args = Args()
    full_dataset = DomainDataset(phish_domain, benign_domain)

    # -------------------------------
    # Train/Val Split
    # -------------------------------
    val_ratio = 0.1
    val_size = int(len(full_dataset) * val_ratio)
    train_size = len(full_dataset) - val_size
    train_dataset, val_dataset = random_split(full_dataset, [train_size, val_size])

    train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True)
    val_loader   = DataLoader(val_dataset, batch_size=128, shuffle=False)

    # -------------------------------
    # Device and Model
    # -------------------------------
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = CharCNN(args).to(device)
    criterion = FocalLoss()

    save_path = f'../models/ablation/{exp_name}/models'
    os.makedirs(save_path, exist_ok=True)
    
    pretrain_model_path = f"../models/ablation/{exp_name}/models/charcnn_pretrain.pth"

   
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    num_epochs = 20
    model_path = os.path.join(save_path, f"charcnn_{index}.pth")

    best_f1 = 0.0
    best_model_state = None

    for epoch in range(num_epochs):
        model.train()
        train_loss = 0
        for x_batch, y_batch in tqdm(train_loader, desc=f"Epoch {epoch+1} - Train"):
            x_batch, y_batch = x_batch.to(device), y_batch.to(device)
            optimizer.zero_grad()
            outputs = model(x_batch).squeeze(1)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * x_batch.size(0)
        train_loss /= len(train_loader.dataset)

        model.eval()
        all_preds, all_labels = [], []
        with torch.no_grad():
            for x_batch, y_batch in val_loader:
                x_batch, y_batch = x_batch.to(device), y_batch.to(device)
                outputs = model(x_batch).squeeze(1)   # shape (N,)
                preds = (outputs > 0).long()
                all_preds.extend(preds.cpu().numpy())
                all_labels.extend(y_batch.cpu().numpy())
        
        f1 = f1_score(all_labels, all_preds, average="macro")
        print(f"Epoch {epoch}: Train Loss={train_loss:.4f}, Val F1={f1:.4f}")

        # -------------------------------
        # Save Best Model
        # -------------------------------
        if f1 > best_f1:
            best_f1 = f1
            best_model_state = model.state_dict()

    # -------------------------------
    # Final Save
    # -------------------------------
    if best_model_state is not None:
        torch.save(best_model_state, model_path)
        print(f"Best model saved with F1={best_f1:.4f}")
    else:
        print("no change to model")

    return len(phish_domain), len(benign_domain)





def train_charcnn_bagging_model(exp_name, phish_domain, benign_domain):

    benign_domain = list(benign_domain)
    random.shuffle(benign_domain) 
    chunk_size = len(benign_domain) // BAGGING_MODEL_NUM
    
    for i in range(BAGGING_MODEL_NUM):
        print(f"Training model{i}")
  
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < BAGGING_MODEL_NUM - 1 else len(benign_domain)
        benign_part = benign_domain[start:end]
       
        a,b = train_charcnn_model(exp_name,phish_domain,benign_part,i)
        print(f'Charcnn{i}:phish:{a},benign:{b}')
        
        

    return len(phish_domain), len(benign_domain)



def check_retrain(exp_name):
    retrain_record_name = exp_name+"_retrain_record"
    collection_retrain = db[retrain_record_name]


    latest_record_list = list(collection_retrain.find().sort("timestamp", -1).limit(2))
 
    

    if len(latest_record_list)==0:
        return 0,0,0,1,collection_retrain
        

    latest_timestamp = latest_record_list[0]["timestamp"] if latest_record_list else None
    
    
    past_domain_data = get_data_from_db(exp_name,latest_timestamp)
    
    
    tp_set = set(past_domain_data["tp"])
    fn_set = set(past_domain_data["fn"])
    fp_set = set(past_domain_data["fp"])
    
    
    is_retrain = 0
    tp = len(tp_set)
    fn = len(fn_set)
    fp = len(fp_set)

    if tp + fp == 0:
        precision = 0 
    else:
        precision = tp / (tp + fp)
    

    if len(latest_record_list)==1:
        precision_condition = False
    else:
        precision_past_1 = latest_record_list[0]["precision"]
        precision_past_2 = latest_record_list[1]["precision"]
        precision_condition = precision_past_2>precision_past_1>precision


    if tp + fn == 0:
        recall = 0 
    else:
        recall = tp / (tp + fn)
    
    if len(latest_record_list)==1:
        recall_condition = False
    else:
        recall_past_1 = latest_record_list[0]["recall"]
        recall_past_2 = latest_record_list[1]["recall"]
        recall_condition = recall>recall_past_1>recall_past_2
        recall_condition = recall_past_2>recall_past_1>recall
        
  
   
     
    if precision_condition or recall_condition:
        is_retrain = 1
        model_version = latest_record_list[0]["model_version"] + 1
    else:
        model_version = latest_record_list[0]["model_version"]

    return precision,recall,model_version,is_retrain,collection_retrain
    


if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--exp_name', required=True, choices=EXP_NAMES)
    parser.add_argument('--neg_sampling', default='redis', choices=['redis', 'tranco'],
                        help='negative sampling source: redis = certstream dedup cache, tranco = Tranco top-1m list')
    args = parser.parse_args()
    
    precision,recall,model_version,is_retrain,collection_retrain = check_retrain(args.exp_name)
    phish_num = 0
    benign_num = 0
    if is_retrain:
        os.makedirs(f"../models/ablation/{args.exp_name}/models", exist_ok=True)
        os.makedirs(f"../models/ablation/{args.exp_name}/data", exist_ok=True)
        
        phish_domain,benign_domain = get_training_data(args.exp_name, neg_sampling=args.neg_sampling)
        
        if "fasttext" in args.exp_name:
            phish_num,benign_num = train_fasttext_bagging_model(args.exp_name,phish_domain,benign_domain)
        elif "charcnn" in args.exp_name:
            phish_num,benign_num = train_charcnn_bagging_model(args.exp_name,phish_domain,benign_domain)
        elif "tfidf" in args.exp_name:
            phish_num,benign_num = train_tfidf_logisticregression_bagging_model(args.exp_name,phish_domain,benign_domain)
       
       
            

    retrain_new_record = {
    "timestamp": datetime.now(),
    "precision": precision,
    "recall": recall,
    "is_retrain": is_retrain,
    "model_version": model_version,
    "phish_num":phish_num,
    "benign_num":benign_num
    }

    collection_retrain.insert_one(retrain_new_record)
    
    
    client.close()
    
   