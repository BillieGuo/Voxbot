# next formatting update: 23/08/2024

import torch
import re
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
from utils import get_path, load_prompt
from dotenv import load_dotenv
import os
import openai
from openai import AzureOpenAI



class LMP:
    def __init__(self, name, cfg, fixed_vars={}, variable_vars={}):
        self.name = name
        self.cfg = cfg
        self.model = None
        self.tokenizer = None
        self.fixed_vars = fixed_vars
        self.variable_vars = variable_vars
        self.load_model()
    
    
    def config(self):
        if 'gpt' in self.cfg['model'] :
            load_dotenv()
            openai.api_type = "azure"
            openai.api_key = os.getenv("OPENAI_API_KEY")
            openai.azure_endpoint = os.getenv("OPENAI_API_ENDPOINT")
            openai.api_version = os.getenv("OPENAI_API_VERSION")
        else:
            self.model_id = get_path(self.cfg['model'])
            
        self.adapter_id = get_path(self.cfg['adapter'])
        self.sys_prompts = load_prompt(self.cfg['sys_prompts'])
        self.user_prompts = load_prompt(self.cfg['user_prompts'])
            
    
    
    def format_chat_template(self, prompt, document=None):
        if (self.variable_vars is None):
            custom_import = ''
        else:
            custom_import = f"from LLM_lib import {', '.join(self.variable_vars.keys())}"
        self.user_prompts = self.user_prompts.replace('{custom_import}', custom_import)
        
        user1 = f"I would like you to help me write Python code to control a robot navigation operating in indoor environment. Please complete the code every time when I give you new query. Pay attention to appeared patterns in the given context code. Be thorough and thoughtful in your code. Do not include any import statement. Do not repeat my question. Do not provide any text explanation (comment in code is okay). I will first give you the context of the code below:\n\n```\n{self.user_prompts}\n```\n\nNote that x is back to front with front is positive x, y is right to left with left is positive y, and z is bottom to up."
        assistant1 = f'Got it. I will complete what you give me next and output the code in plain text only without code block.'
        if (self.cfg['heirarchy'] == 'preview'):
            user1 = f"{self.user_prompts}"
            assistant1 = f'Got it. I will complete what you give me next.'
        prompt = f'Query: {prompt}'
        messages = [
            {"role": "system", "content": self.sys_prompts},
            {"role": "user",   "content": user1},
            {"role": "assistant", "content": assistant1},
            {"role": "user",   "content": prompt+'\n'},
        ]
        if 'gpt' in self.cfg['model']:
            return messages
        
        input_ids = self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            documents=document,
            return_tensors="pt"
        ).to("cuda")
        return input_ids
    
    
    def code_formatting(self, code):
        if self.cfg['heirarchy'] == 'low': # lower level LLM
            code_prefix = f"import {', '.join(self.fixed_vars.keys())}"+ f"\ncommands = ['source ~/interbotix_ws/install/setup.bash', '''{code}''']\n"
        else:
            code_prefix = f"import {', '.join(self.fixed_vars.keys())}\n"
            return code_prefix + code
        code_suffix = f"for command in commands:\n\tresult = subprocess.run(command, shell=True, executable='/bin/bash', capture_output=True, text=True)"
        return code_prefix + code_suffix

    
    def generate(self, input_ids):
        try:
            if 'gpt' in self.cfg['model']:
                chat_completion = openai.chat.completions.create(
                    model="trygpt4o", # Do not edit this. model="deployment_name"
                    messages=input_ids,
                    temperature=0.0, 
                    max_tokens=self.cfg['max_new_tokens'], 
                    n=1)
                result = chat_completion.choices[0].message.content
                # print("**"*80)
                # print(result)
                # print("**"*80)
                # pattern = r'```python\n(.*)```'
                # final = re.findall(pattern, result, re.DOTALL)[-1]
                final = result
            else:
                self.model.eval()
                with torch.no_grad():
                    result = self.tokenizer.decode(self.model.generate(inputs=input_ids, max_new_tokens=self.cfg['max_new_tokens'], pad_token_id=self.tokenizer.eos_token_id)[0], skip_special_tokens=True)
                    # result = self.tokenizer.decode(self.model.generate(**input_ids, max_new_tokens=1000, pad_token_id=self.tokenizer.eos_token_id)[0], skip_special_tokens=True)
            
                # Define regular expression pattern to extract the behavior tree from the complete output
                # depends on the prompt
                # pattern = r'assistant(.*?)# done' 
                pattern = r'assistant\n(.*)'
                matches = re.findall(pattern, result, re.DOTALL)
                # print("="*80)
                # print(result)
                # print("="*80)
                # print(matches[-1])
                # print("="*80)
                final = re.findall(r'assistant(.*)', matches[-1], re.DOTALL)[-1]
            
            # print(final)
            # print(type(final))
            # print("="*80)
            
            # special case
            if not final:
                return None
            if self.cfg['heirarchy'] == 'preview':
                return final, True
            
            success = True
            # # execute the code
            # gvars = self.fixed_vars | self.variable_vars
            # lvars = {}
            # code = self.code_formatting(final)
            # success = safe_to_run(code, gvars, lvars)
            # if success: #and self.cfg['save_output']:
            #     print(lvars['result'])
        except KeyboardInterrupt:
            print("KeyboardInterrupt")
            return None, True
        
        return final, success
    
    
    def load_model(self):
        # config
        self.config()
        if 'gpt' in self.cfg['model']:
            self.model = AzureOpenAI(
                api_key = os.getenv("OPENAI_API_KEY"),
                api_version = os.getenv("OPENAI_API_VERSION"),
                azure_endpoint = os.getenv("OPENAI_API_ENDPOINT")
                )
            return
        else:
            quantization_config = BitsAndBytesConfig(load_in_4bit=True) if self.cfg['load_in_4bit'] \
                                else BitsAndBytesConfig(load_in_8bit=True)
            token = "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"

            # Load base model
            base_model = AutoModelForCausalLM.from_pretrained(
                pretrained_model_name_or_path = self.model_id,
                quantization_config = quantization_config,
                torch_dtype = torch.float16,
                device_map = {"":0}, #auto
                # trust_remote_code = True,
                token=token,
                local_files_only=True, # local LLM
            )
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                pretrained_model_name_or_path = self.model_id, 
                token=token,
                local_files_only=True
            )
            
            if self.adapter_id is None:
                self.model = base_model
                return
            # Load fine-tuned model
            finetuned_model = PeftModel.from_pretrained(base_model, self.adapter_id, device_map = {"":0},)
            # finetuned_model = finetuned_model.merge_and_unload()

            device = torch.device("cuda")# if torch.cuda.is_available() else "cpu")
            finetuned_model = finetuned_model.to(device)
            self.model = finetuned_model
            return
    
    def __call__(self, prompt):
        input_text = self.format_chat_template(prompt)
        return self.generate(input_text)
    
# execute module
def safe_to_run(code, gvars=None, lvars=None):    
    forbidden = ['__','exec(','eval']
    for word in forbidden:
        assert word not in code, f'forbidden word "{word}" in code'
    if gvars is None:
        gvars = {}
    if lvars is None:
        lvars = {}
    try:
        print("="*80)
        print(code)
        print(type(code))
        print("="*80)
        exec(code, gvars, lvars)
        return True
    except Exception as e:
        print(f'Error codes: {e}')
        return False
    