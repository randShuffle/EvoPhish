   
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
from transformers import AutoModelForSequenceClassification,AutoConfig,DataCollatorWithPadding
import pickle
import pandas as pd
import shutil
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

HOSTING_PLATFORMS = {
 '4everland.app',
 'amazonaws.com',
 'amplifyapp.com',
 'azurewebsites.net',
 'backblazeb2.com',
 'biz.id',
 'cloudaccess.host',
 'cloudfront.net',
 'cloudwaysapps.com',
 'contabostorage.com',
 'daftpage.com',
 'digitaloceanspaces.com',
 'firebaseapp.com',
 'format.com',
 'framer.app',
 'framer.website',
 'github.io',
 'godaddysites.com',
 'hostingersite.com',
 'kinsta.cloud',
 'linodeobjects.com',
 'mmm.page',
 'my.id',
 'mystrikingly.com',
 'netlify.app',
 'on-fleek.app',
 'ondigitalocean.app',
 'pages.dev',
 'plesk.page',
 'r2.dev',
 'replit.app',
 'replit.dev',
 'rollout.site',
 'squarespace.com',
 'surge.sh',
 'trycloudflare.com',
 'typedream.app',
 'univer.se',
 'vercel.app',
 'web.app',
 'webflow.io',
 'weebly.com',
 'weeblysite.com',
 'wixsite.com',
 'wixstudio.com',
 'wixstudio.io',
 'workers.dev',
 'wpenginepowered.com',
 'zeabur.app'
}


def transform_domain(domains):
    transformed_domains = set()
    for domain in domains:
        for hosting_platform in HOSTING_PLATFORMS:
            if domain.endswith(hosting_platform):
                domain = domain[:-len(hosting_platform)]
                if domain.endswith('.'):
                    domain = domain[:-1]
                break
        transformed_domains.add(domain)
    return list(transformed_domains)










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






username = "yourusername"
password = "yourpassword"
MONGO_URI = f'mongodb://{username}:{password}@localhost:27019/'
DB_NAME = 'certstream'
client = MongoClient(MONGO_URI)
db = client[DB_NAME]




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
    
    


def get_training_data(exp_name,start_time=None):
    
    past_db_data = get_data_from_db(exp_name)
    tp = set(past_db_data["tp"])
    fp = set(past_db_data["fp"])
    tn = set(past_db_data["tn"])
    fn = set(past_db_data["fn"])
    
    print(len(tp),len(fp),len(tn),len(fn))
    
    phish_domain = tp | fn
    
    benign_needed = len(phish_domain)*BAGGING_MODEL_NUM
    half = benign_needed // 2


    fp_needed = half
    tn_needed = benign_needed - fp_needed

    fp_sample = set(random.sample(fp, min(len(fp), fp_needed)))
    tn_sample = set(random.sample(tn, min(len(tn), tn_needed)))


    if len(fp_sample) < fp_needed:
        short = fp_needed - len(fp_sample)
        tn_extra_candidates = list(tn - tn_sample)
        tn_sample |= set(random.sample(tn_extra_candidates, min(len(tn_extra_candidates), short)))


    if len(tn_sample) < tn_needed:
        short = tn_needed - len(tn_sample)
        fp_extra_candidates = list(fp - fp_sample)
        fp_sample |= set(random.sample(fp_extra_candidates, min(len(fp_extra_candidates), short)))

    benign_domain = tn_sample | fp_sample
    
    
    
    
    print(f'phish size:{len(phish_domain)},benign size:{len(benign_domain)}')
    return transform_domain(phish_domain),transform_domain(benign_domain)
    
    
def get_fixed_benign_domains():
    fixed_benign_domains_list = []
    
    with open('../datasets/phishpedia/domain_map.pkl', 'rb') as f:
        domain_map = pickle.load(f)
        
    for k,v in domain_map.items():
        fixed_benign_domains_list.extend(list(v))
        
    df = pd.read_csv('../datasets/raw/tranco_1m_subdomains.csv', header=None, names=['id', 'domain'])
    tranco_list = df["domain"][:10000].tolist()
    
    fixed_benign_domains_list.extend(tranco_list)
    fixed_benign_domains_list = transform_domain(fixed_benign_domains_list)
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
        benign_fixed_domains = get_fixed_benign_domains()
        tol_benign_nums = len(benign_part)
        half = tol_benign_nums//2
        
        benign_fixed_domains_sample = list(random.sample(benign_fixed_domains, min(len(benign_fixed_domains), half)))
        benign_part_sample = list(random.sample(benign_part, len(benign_part)-len(benign_fixed_domains_sample)))

        benign_final = benign_fixed_domains_sample+benign_part_sample
        
        
        
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
        benign_fixed_domains = get_fixed_benign_domains()
        tol_benign_nums = len(benign_part)
        half = tol_benign_nums//2
        
        benign_fixed_domains_sample = list(random.sample(benign_fixed_domains, min(len(benign_fixed_domains), half)))
        benign_part_sample = list(random.sample(benign_part, len(benign_part)-len(benign_fixed_domains_sample)))

        benign_final = benign_fixed_domains_sample+benign_part_sample
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
        benign_fixed_domains = get_fixed_benign_domains()
        tol_benign_nums = len(benign_part)
        half = tol_benign_nums//2
        
        benign_fixed_domains_sample = list(random.sample(benign_fixed_domains, min(len(benign_fixed_domains), half)))
        benign_part_sample = list(random.sample(benign_part, len(benign_part)-len(benign_fixed_domains_sample)))

        benign_final = benign_fixed_domains_sample+benign_part_sample
       
        a,b = train_charcnn_model(exp_name,phish_domain,benign_part,i)
        print(f'Charcnn{i}:phish:{a},benign:{b}')
        
        

    return len(phish_domain), len(benign_domain)



def train_canine_model(exp_name, phish_domain, benign_domain,index=None):
    url_list = []
    for domain in phish_domain:
        url_list.append({"url":domain,"label":1})
    
    for domain in benign_domain:
        url_list.append({"url":domain,"label":0})
    
    
    def preprocess_function(examples, tokenizer):
        return tokenizer(
            examples['url'],
            truncation=True,
            max_length=64,
            padding="max_length"
        )

    def encode_labels(examples):
        return {'labels': examples['label']}
    
    
    def compute_metrics(eval_pred):
        logits, labels = eval_pred
        predictions = logits.argmax(axis=1)
        accuracy = accuracy_score(labels, predictions)
        return_dict = {}
        return_dict['accuracy'] = accuracy

        average_type_list = ["binary","macro","micro","weighted"]
        
        for average in average_type_list:
            precision = precision_score(labels, predictions, average=average,zero_division=0)
            recall = recall_score(labels, predictions, average=average,zero_division=0)
            f1 = f1_score(labels, predictions, average=average,zero_division=0)
            return_dict[average+"_precision"]  = precision
            return_dict[average+"_recall"]  = recall
            return_dict[average+"_f1"]  = f1
            
            
        return return_dict


    
    model_path = "../models/raw/canine-c"
        
    dataset = Dataset.from_list(url_list)
    dataset = dataset.train_test_split(test_size=0.1, seed=42)
    

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    config = AutoConfig.from_pretrained(model_path)
    
    
    config.hidden_size=128
    config.intermediate_size=512
    config.num_attention_heads = 4
    config.num_hidden_layers = 1
    config.problem_type = "single_label_classification"
    config.pad_token_id = tokenizer.pad_token_id
    config.num_labels = 2
  
    tokenized_dataset = dataset.map(
        lambda x: preprocess_function(x, tokenizer),
        num_proc=4,
    )
    tokenized_dataset = tokenized_dataset.map(encode_labels, num_proc=4) 
 
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
    
   
    # model = AutoModelForSequenceClassification.from_pretrained(
    # model_path,)
    model = AutoModelForSequenceClassification.from_config(config)
    #torch_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
    lr = 2e-4
    epochs = 3
    eval_steps = 10
    save_steps = 10
    output_dir = f"../models/ablation/{exp_name}/models/{index}"
   
            

    
   
    training_args = TrainingArguments(
    output_dir=output_dir,
    eval_strategy="epoch",
    learning_rate=lr,
    per_device_train_batch_size=128,
    per_device_eval_batch_size=1024,
    num_train_epochs=epochs,
    weight_decay=0.01,
    logging_steps=10,
    logging_first_step=True,
    save_strategy="epoch", 
    save_steps=None,  
    load_best_model_at_end=True,
    fp16=not torch.cuda.is_bf16_supported(),
    bf16=torch.cuda.is_bf16_supported(),
    tf32=True,
    dataloader_num_workers=8,
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    save_total_limit=2,
    label_names=["labels"],
    ddp_find_unused_parameters=True,
    metric_for_best_model="binary_f1",  
    greater_is_better=True,     
)

    



    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["test"],
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics
    )


    trainer.train()


    save_path = f"../models/ablation/ablation_canine_phishintention/models/{index}/best"

    model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)


    return len(phish_domain),len(benign_domain)
    
    
    

def train_canine_bagging_model(exp_name, phish_domain, benign_domain):

    benign_domain = list(benign_domain)
    random.shuffle(benign_domain)
    chunk_size = len(benign_domain) // BAGGING_MODEL_NUM
    
    for i in range(BAGGING_MODEL_NUM):
        print(f"Training model{i}")

        start = i * chunk_size
        end = (i + 1) * chunk_size if i < BAGGING_MODEL_NUM - 1 else len(benign_domain)
        benign_part = benign_domain[start:end]
        benign_fixed_domains = get_fixed_benign_domains()
        tol_benign_nums = len(benign_part)
        half = tol_benign_nums//2
        
        benign_fixed_domains_sample = list(random.sample(benign_fixed_domains, min(len(benign_fixed_domains), half)))
        benign_part_sample = list(random.sample(benign_part, len(benign_part)-len(benign_fixed_domains_sample)))

        benign_final = benign_fixed_domains_sample+benign_part_sample
       
       
        a,b = train_canine_model(exp_name,phish_domain,benign_part,i)
        print(f'Charcnn{i}:phish:{a},benign:{b}')
        
    return len(phish_domain), len(benign_domain)







def train_ood_model(exp_name,phish_domains,benign_domains):
    typo_model = IsTypo(model_dir=TYPO_MODEL_DIR)
    all_domains = list(phish_domains)+list(benign_domains)
    all_embeddings = typo_model.get_embeddings(all_domains).cpu().numpy()
   

    faiss_index = FaissIVFFlatIndex(num_vectors=len(all_embeddings), d=768, gpu_id=0)
    faiss_index.index.train(all_embeddings)
    faiss_index.index.add(all_embeddings)
    
    save_dir = os.path.join("..", "models", "ablation", exp_name, "faiss")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "faiss.index")
    cpu_index = faiss.index_gpu_to_cpu(faiss_index.index)

    faiss.write_index(cpu_index, save_path)
    print(f"[INFO] Faiss index saved to: {save_path}")
    

from transformers import AutoTokenizer, AutoModelForMaskedLM
from transformers import DataCollatorForLanguageModeling
from datasets import Dataset
from transformers import Trainer, TrainingArguments
import math
def train_ood_model_mlm(exp_name, phish_domains, benign_domains):
    raw_model_path = "../models/raw/tinybert"
    all_domains = phish_domains+benign_domains
    
    tokenizer = AutoTokenizer.from_pretrained(raw_model_path)
    model = AutoModelForMaskedLM.from_pretrained(raw_model_path)
    dataset = Dataset.from_dict({"text": all_domains})


    dataset = dataset.train_test_split(test_size=0.1, seed=42)
    
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer, 
        mlm=True, 
        mlm_probability=0.2
    )

    def tokenize_function(examples):
        return tokenizer(
            examples["text"], 
            truncation=True, 
            padding="max_length", 
            max_length=64
        )

    tokenized_dataset = dataset.map(tokenize_function, num_proc=4, remove_columns=["text"])
    
    save_dir = f"../models/ablation/{exp_name}/ood"
    os.makedirs(save_dir, exist_ok=True)
    
    training_args = TrainingArguments(
        output_dir=save_dir,
        evaluation_strategy="steps",
        eval_steps=100,
        logging_steps=100,
        save_steps=100,
        per_device_train_batch_size=2048,
        per_device_eval_batch_size=2048,
        num_train_epochs=5,
        weight_decay=0.01,
        learning_rate=5e-5,
        save_total_limit=2,
        report_to="none", 
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False, 
    )


    def compute_metrics(eval_pred):
        loss = eval_pred.metrics["eval_loss"]
        try:
            perplexity = math.exp(loss)
        except OverflowError:
            perplexity = float("inf")
        return {"perplexity": perplexity, "eval_loss": loss}

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["test"],
        tokenizer=tokenizer,
        data_collator=data_collator,
    )

    trainer.train()
 
    final_dir = os.path.join(save_dir, "final")
    os.makedirs(final_dir, exist_ok=True)
    trainer.save_model(final_dir)

    eval_results = trainer.evaluate()
    print("Final evaluation:", eval_results)



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
    args = parser.parse_args()
    
    precision,recall,model_version,is_retrain,collection_retrain = check_retrain(args.exp_name)
    phish_num = 0
    benign_num = 0
    if is_retrain:
        os.makedirs(f"../models/ablation/{args.exp_name}/models", exist_ok=True)
        os.makedirs(f"../models/ablation/{args.exp_name}/data", exist_ok=True)
        
        phish_domain,benign_domain = get_training_data(args.exp_name)
        
        if "fasttext" in args.exp_name:
            phish_num,benign_num = train_fasttext_bagging_model(args.exp_name,phish_domain,benign_domain)
        elif "charcnn" in args.exp_name:
            phish_num,benign_num = train_charcnn_bagging_model(args.exp_name,phish_domain,benign_domain)
        elif "tfidf" in args.exp_name:
            phish_num,benign_num = train_tfidf_logisticregression_bagging_model(args.exp_name,phish_domain,benign_domain)
        elif "canine" in args.exp_name:
            phish_num,benign_num = train_canine_bagging_model(args.exp_name,phish_domain,benign_domain)
            
            
       
            

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
    
   