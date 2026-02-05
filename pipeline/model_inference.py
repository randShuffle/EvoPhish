import fasttext
from collections import Counter
import numpy as np
import os
import joblib
import fasttext
from sentence_transformers import SentenceTransformer
import pickle
from sentence_transformers.util import cos_sim
from common import DOMAIN_MAP_DIR,BAGGING_MODEL_NUM
import json
import torch
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import faiss
import faiss.contrib.torch_utils
from transformers import AutoModelForSequenceClassification

class CharCNN(nn.Module):
    def __init__(self, args):
        super(CharCNN, self).__init__()
        
        self.conv1 = nn.Sequential(
            nn.Conv1d(args.num_features, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            # nn.MaxPool1d(kernel_size=2, stride=2)
        )
        
        self.conv2 = nn.Sequential(
            nn.Conv1d(128, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            # nn.MaxPool1d(kernel_size=2, stride=2)
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





class FastTextSingle:
    def __init__(self, model_dir) -> None:
        self.model = fasttext.load_model(model_dir)
        
    def inference(self, domain_list):

        if not isinstance(domain_list, list):
            domain_list = [domain_list]
            

        all_labels, all_scores = self.model.predict(domain_list, k=2)
        
        probability_list = []
        prediction_list = []
        for domain, labels, scores in zip(domain_list, all_labels, all_scores):
    
            score_dict = {label.replace("__label__", ""): score 
                         for label, score in zip(labels, scores)}
            
            prob_pos = score_dict.get("1", 0.0)
            

            max_score = -1
            final_label = "0"
            for label, score in score_dict.items():
                if score > max_score:
                    max_score = score
                    final_label = label
            
            probability_list.append(float(prob_pos))
      
            
            
        return probability_list




class FastTextBagging:
    def __init__(self, model_dir) -> None:

        self.models = []
        for file in os.listdir(model_dir):
            model_path = os.path.join(model_dir, file)
     
            try:
                model = fasttext.load_model(model_path)
                self.models.append(model)
            except:
                print(f"skip: {model_path}")
        
        if not self.models:
            raise ValueError(f"skip {model_dir}")

    def inference(self, domain_list):
        if not isinstance(domain_list, list):
            domain_list = [domain_list]
        return self.soft_vote_inference(domain_list)
        
        

    def soft_vote_inference(self, domain_list, threshold=0.5):

        all_probabilities = []
        

        for model in self.models:
            labels, scores = model.predict(domain_list, k=2)
            
 
            probs = []
            for domain_labels, domain_scores in zip(labels, scores):
                score_dict = {label.replace("__label__", ""): score 
                             for label, score in zip(domain_labels, domain_scores)}
                probs.append(score_dict.get("1", 0.0))
            
            all_probabilities.append(probs)
        
   
        probability_list = []
     
        for domain_idx, domain in enumerate(domain_list):
      
            domain_probs = [model_probs[domain_idx] for model_probs in all_probabilities]
            
            avg_prob_pos = np.mean(domain_probs)
            prediction = 1 if avg_prob_pos >= threshold else 0
            probability_list.append(float(avg_prob_pos))
            
        
        return probability_list
    



class TfIdfLogisticRegression:
    def __init__(self,model_dir) -> None:

        self.models = []
        for file in os.listdir(model_dir):
            model_path = os.path.join(model_dir, file)
           
            try:
                model = joblib.load(model_path)
                self.models.append(model)
            except:
                print(f"skip: {model_path}")
        
        if not self.models:
            raise ValueError(f"skip {model_dir}")
    
    def inference(self,domain_list):
        all_probs = []
        for model in self.models:
            probs = model.predict_proba(domain_list)[:, 1]
            all_probs.append(probs)
        return list(np.mean(all_probs, axis=0))


class CharCNNInference:
    def __init__(self, model_dir, alphabet_path="./alphabet.json", max_len=64, device=None):
        with open(alphabet_path, "r", encoding="utf-8") as f:
            self.vocab_list = json.load(f)
        self.char2idx = {c: i + 1 for i, c in enumerate(self.vocab_list)} 
        self.max_len = max_len

 
        if device is None:
            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
 
        self.device = device


        class Args:
            num_features = len(self.vocab_list) + 1 
            dropout = 0.5

        args = Args()
        
        self.models = []
        for i in range(BAGGING_MODEL_NUM):
            model_path = os.path.join(model_dir,f"charcnn_{i}.pth")

            try:
                model = CharCNN(args)
                state_dict = torch.load(model_path, map_location="cpu")
                model.load_state_dict(state_dict)
                model.to(self.device)
                model.eval()
                self.models.append(model)
            except Exception as e:
                print(f"skip: {model_path}")
        
        if not self.models:
            raise ValueError(f"skip {model_dir}")
        
        
        

    def encode_domain(self, domain):
        x = np.zeros((len(self.vocab_list) + 1, self.max_len), dtype=np.float32)
        for i, c in enumerate(domain[:self.max_len]):
            if c in self.char2idx:
                x[self.char2idx[c], i] = 1.0
        return x


    def encode_domain_batch(self, domains):

        batch_size = len(domains)

        x = np.zeros((batch_size, len(self.vocab_list) + 1, self.max_len), dtype=np.float32)
        
        for i, domain in enumerate(domains):

            domain = domain.lower()[:self.max_len]
            for j, c in enumerate(domain):
                idx = self.char2idx.get(c, 0) 
                x[i, idx, j] = 1.0
                
        return x
    
    def inference(self, domains):
  
        encoded = self.encode_domain_batch(domains)
        x_tensor = torch.tensor(encoded, dtype=torch.float32).to(self.device)
        probs_list = []
        for i in range(BAGGING_MODEL_NUM):
            with torch.no_grad():
                outputs = self.models[i](x_tensor).squeeze(1)
                probs = torch.sigmoid(outputs).cpu().numpy()
                probs_list.append(probs)


        avg_probs = sum(probs_list) / BAGGING_MODEL_NUM
       
        return [float(p) for p in avg_probs]

        


class CanineInference():
    def __init__(self, model_dir,device=None) -> None:

        if device is None:
            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
 
        self.device = device
        
        
        self.models = []
        for i in range(BAGGING_MODEL_NUM):
            model_path = f'{model_dir}/{i}/best'

            try:
                model = AutoModelForSequenceClassification.from_pretrained(
                    model_path,
                )
                
                model.to(self.device)
                model.eval()
                self.models.append(model)
            except:
                print(f"skip: {model_path}")
        
        self.tokenizer = AutoTokenizer.from_pretrained("../models/raw/canine-c")
        if not self.models:
            raise ValueError(f"skip {model_dir}")
        
        
    def inference(self, domains):
      
        inputs = self.tokenizer(domains, padding=True, truncation=True, return_tensors="pt").to(self.device)

    
        probs_list = []
        
        for i,model in enumerate(self.models):
            with torch.inference_mode():
                outputs = model(**inputs)
      
                probs = torch.sigmoid(outputs.logits).cpu().numpy()
                
                probs_list.append(probs[:,1])


        avg_probs = sum(probs_list) / BAGGING_MODEL_NUM
        
   
        return [float(p) for p in avg_probs]
               









class IsOod:
    def __init__(self,model_dir) -> None:
        gpu_id = 0
        cpu_index = faiss.read_index(model_dir)

        res = faiss.StandardGpuResources()
        self.gpu_index = faiss.index_cpu_to_gpu(res, gpu_id, cpu_index)
        self.gpu_index.nprobe = 32
    
    def get_max_similarity(self,domain_embeddings,k=10):
        
        domain_embeddings = domain_embeddings
      
        D, I = self.gpu_index.search(domain_embeddings, k=k)
       
        return (torch.sum(D,dim=1).cpu()/k).tolist()






    
class IsTypo:
    def __init__(self,model_dir) -> None:
        self.ts = 0.8
        self.model = SentenceTransformer(model_dir)
        with open(DOMAIN_MAP_DIR,'rb') as f:
            domain_map = pickle.load(f)
        whitelist_domains = []
        for k,v in domain_map.items():
            whitelist_domains.extend(v)
        self.whitelist_embeddings = self.get_embeddings(whitelist_domains)
        print("whitelist embedding init finish...")
        
        
    def get_embeddings(self,domain_list):
        batch_embeddings = self.model.encode(domain_list,batch_size=1000,
                                    show_progress_bar=False, convert_to_tensor=True,normalize_embeddings=True)
        return batch_embeddings
        
    
    def inference(self,domain_list):
        domain_list_embeddings = self.get_embeddings(domain_list)
        similarity_matrix = cos_sim(domain_list_embeddings,self.whitelist_embeddings)
        max_sim_values, _ = similarity_matrix.max(dim=1)
        results = [
            1 if max_sim.item() > self.ts else 0
            for max_sim in max_sim_values
        ]
        return domain_list_embeddings,results
        
     
     

import os
import torch
import math
from transformers import AutoTokenizer, AutoModelForMaskedLM, DataCollatorForLanguageModeling
from tqdm import tqdm
class OODPerplexity:
    def __init__(self, model_dir):
  
        self.device = "cuda:0"
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForMaskedLM.from_pretrained(model_dir).to(self.device)
        self.model.eval()
       
        self.data_collator = DataCollatorForLanguageModeling(
            tokenizer=self.tokenizer,
            mlm=True,
            mlm_probability=0.15
        )
        print("OODPerplexity model init finish...")

    def compute_ppl_for_list(self, text_list):

        per_text_ppl = []
        
        for text in tqdm(text_list):

            encoding = self.tokenizer(text, truncation=True, padding="max_length", max_length=64, return_tensors="pt")
            input_ids = encoding["input_ids"].to(self.device)

            batch = self.data_collator([{"input_ids": input_ids[0]}])
            batch = {k: v.to(self.device) for k, v in batch.items()}
            

            with torch.no_grad():
                outputs = self.model(**batch)
                loss = outputs.loss 
            
  
            try:
                ppl = math.exp(loss.item())
            except OverflowError:
                ppl = float("inf")
            
            per_text_ppl.append(ppl)
        
        return per_text_ppl


        


  