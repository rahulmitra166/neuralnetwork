#%%
import os
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
#%%
flow_type = np.genfromtxt('FlowStructure_2022_03_24_total.dat', dtype=str)
vol_data = np.genfromtxt('points_vol.dat', skip_header=1)
velocity_data = np.load('data.npy')

labels = np.unique(flow_type[:,1])
label2id = {k:v for k,v in enumerate(labels)}
id2label = {v:k for k,v in label2id.items()}


x_bins = np.linspace(start = vol_data[:,0].min(), stop=vol_data[:,0].max(), num=15)
y_bins = np.linspace(start = vol_data[:,1].min(), stop=vol_data[:,1].max(), num=15)
z_bins = np.linspace(start = vol_data[:,2].min(), stop=vol_data[:,2].max(), num=30)

velocity_data_sliced = velocity_data[int(flow_type[0][0]):int(flow_type[-1][0])+1, :, :]
new_velocity_data = np.zeros((10800, 15, 15, 30, 3))

for i in range(len(vol_data)):
    coords = vol_data[i]
    # print(coords)
    x_grid = max(max(np.where(x_bins<=coords[0])))
    # print(x_grid)
    y_grid = max(max(np.where(y_bins<=coords[1])))
    # print(y_grid)
    z_grid = max(max(np.where(z_bins<=coords[2])))
    print(x_grid, y_grid, z_grid)

    new_velocity_data[:, x_grid, y_grid, z_grid, :] = velocity_data_sliced[:, i, :]

#%%

"""
Three Golden Properties of Object Oriented Programming:
1. Inheritance  -> Subclassing
2. Polymorphism -> Method Overriding
3. Encapsulation-> Subclassing
"""

#   A more modular way to write the model would be to first write the subparts of the model and then
#   Subclass it for higher order blocks till you reach the complete model.
#   We will attempt to do that later...

class ConvBlock3D(nn.Module):
    def __init__(
        self, in_channels, out_channels, kernel_size, stride, padding, 
        output_size, activation=None, dropout=0, pool_type='max'
    ):
        super(ConvBlock3D, self).__init__()
        self.activation = nn.Identity()
        if activation:
            assert activation in ["relu", "gelu", "swish"], "Currently supported activations: relu, gelu, swish"
            act_dict = {
                "relu": nn.ReLU(),
                "gelu": nn.GELU(),
                "swish" :nn.SiLU(),
            }
            self.activation = act_dict[activation]

        assert pool_type in ["max", "avg"], "Pool type must be max or avg"
        assert type(output_size)==tuple, "Output Size must be a tuple"
        assert len(output_size)==3, "Output size must have 3 dimensions"

        if pool_type=='avg':
            self.pooler = nn.AdaptiveAvgPool3d(output_size=output_size)
        else:
            self.pooler = nn.AdaptiveMaxPool3d(output_size=output_size)
        
        self.conv_block = nn.Sequential(
            nn.Conv3d(
                in_channels=in_channels, out_channels=out_channels, kernel_size=kernel_size, stride=stride, padding=padding
            ),
            self.pooler,
            self.activation,
            nn.Dropout(p=dropout)    
        )

    def forward(self, input):
        x = input
        x = self.conv_block(x)
        return x


class ClassifierModel(nn.Module):

    #   Constructor Function:
    def __init__(self, num_classes, id2label, label2id, ):
        super(ClassifierModel, self).__init__()
        # self.conv_block = nn.Sequential(
        #     ConvBlock3D(
        #         in_channels=3, out_channels=16, kernel_size=3, stride=1, padding='same',
        #         output_size=(8, 8, 16), activation='gelu', dropout=0.25, pool_type='max'
        #     ),
        #     ConvBlock3D(
        #         in_channels=16, out_channels=32, kernel_size=3, stride=1, padding='same',
        #         output_size=(4, 4, 8), activation='gelu', dropout=0.25, pool_type='max'
        #     ),
        #     ConvBlock3D(
        #         in_channels=32, out_channels=64, kernel_size=3, stride=1, padding='same',
        #         output_size=(2, 2, 4), activation='gelu', dropout=0.25, pool_type='max'
        #     ),
        #     ConvBlock3D(
        #         in_channels=64, out_channels=128, kernel_size=3, stride=1, padding='same',
        #         output_size=(1, 1, 2), activation='gelu', dropout=0.25, pool_type='avg'
        #     ),
        # )
        
        self.conv = nn.Conv3d(in_channels=3, out_channels=32, kernel_size=7, stride=2, padding='valid')
        self.bn = nn.BatchNorm3d(32)
        self.pool = nn.AdaptiveMaxPool3d(output_size=(2, 2, 3))
        self.flatten = nn.Flatten()
        # self.lin = nn.Linear(in_features=1728, out_features=256)
        self.classifier = nn.Sequential(
            nn.Linear(in_features=384, out_features=128),
            nn.LeakyReLU(),
            nn.Dropout(0.2),
            nn.Linear(in_features=128, out_features=32),
            nn.LeakyReLU(),
            nn.Dropout(0.2),
            # nn.Linear(in_features=128, out_features=32),
            # nn.LeakyReLU(),
            nn.Linear(in_features=32, out_features=num_classes)
        )
        self.config = {}
        self.config['id2label']=id2label
        self.config['label2id']=label2id
        self.config['num_classes']=num_classes
        self.loss_fc = nn.CrossEntropyLoss(reduction='mean')
        self.model_compiled=False
        self.train_metric = []
        self.trainable_params = [p for p in self.parameters()]

    #   Call Function/Default Function:
    def forward(self, input):
        x = input
        x = self.conv(x)
        x = self.pool(x)
        x = self.bn(x)
        x = self.flatten(x)
        x = self.classifier(x)
        return x
    
    def predict(self, input):
        """
        If you want to pass one time step: i.e. input.shape = 19875
        input = input.unsqueeze(0)
        input shape has to be (n, 19875)
        """
        output = self(input)
        pred = output.argmax(dim=-1)
        return pred
    
    def predict_classes(self, input):
        pred = self.predict(input)
        return [self.config['id2label'][str(i)] for i in pred]

    def create_optimizer(self):
        trainable_params = [p for p in self.parameters() if p.requires_grad==True]
        self.optimizer = torch.optim.Adam(params=trainable_params, lr = 5e-3)

    def train_one_epoch(self, train_data, test_data, epoch):
        if self.optimizer is None:
            self.create_optimizer()
        """
        The function currently assumes you call this via model.fit()
        model.compile needs to be invoked before model.fit can be used.
        """
        print(f"Currently Training {epoch+1}/{self.max_epochs} epoch")
        for idx, data in enumerate(train_data):
            if idx%10==0:
                print(f"Batch {idx}/{len(train_data)}...")
            one_batch_of_data = data[0]
            one_batch_of_target = data[1]
            self.train()
            self.training_step(one_batch_of_data, one_batch_of_target)

        if self.metric is not None:
            assert test_data is not None, "You must provide test data if you want to print any performance metric"
            assert self.metric in ["accuracy", "f1", "confusion"], "Invalid metric argument"
            self.eval()
            conf_mat = self.confusion_matrix(test_data)
            if self.metric=="confusion":
                print(f"Confusion Matrix after epoch {epoch+1}: \n{conf_mat}")
                performance_logger = conf_mat
            elif self.metric=="accuracy":
                acc = self.compute_accuracy(conf_mat)
                print(f"Accuracy after epoch {epoch+1}: {acc*100}%")
                performance_logger = acc
            elif self.metric=="f1":
                p, r, f1 = self.prec_rec(conf_mat)
                print(f"After epoch {epoch+1}:")
                print(f"Precision: {p}\nRecall: {r}\nF1 Scores: {f1}")
                performance_logger = torch.mean(f1)

            self.training_logs(performance_logger, epoch)


    def training_step(self, one_batch_of_data, one_batch_of_target):
        output = self(one_batch_of_data.to('cuda'))
        label = one_batch_of_target.to('cuda')
        loss = self.loss_fc(output, label)
        self.optimizer.zero_grad()  
        loss.backward()
        self.optimizer.step()
        
    def fit(self, train_data, test_data=None, epochs=1):
        assert self.model_compiled==True, "Model needs to be compiled before the fit function can be called."
        if not os.path.exists("./results/"):
            os.mkdir("./results")
        if not os.path.exists("./results/checkpoints"):
            os.mkdir("./results/checkpoints")
        if not os.path.exists("./results/training_logs"):
            os.mkdir("./results/training_logs")
        self.max_epochs = epochs
        for epoch in range(epochs):
            print("Currently training epoch %s out of %s" %(epoch, epochs))
            self.train_one_epoch(train_data, test_data, epoch)

    def compute_accuracy(self, conf_mat):
        acc = conf_mat.trace()/conf_mat.sum()
        return acc

    def confusion_matrix(self, test_data):
        conf_mat = torch.zeros(size=(self.config['num_classes'], self.config['num_classes']))
        for idx, data in enumerate(test_data):
            input = data[0]
            target = data[1]
            with torch.no_grad():
                output = self(input)
            pred = output.argmax(dim=-1)
            for i in range(len(target)):
                conf_mat[pred[i]][target[i]]+=1  
        return conf_mat
    
    def prec_rec(self, conf_mat):
        p_matrix = torch.zeros(size=len(conf_mat))
        r_matrix = torch.zeros(size=len(conf_mat))
        for i in range(len(conf_mat)):
            p_matrix[i] = conf_mat[i][i]/torch.sum(conf_mat[i])
            r_matrix[i] = conf_mat[i][i]/torch.sum(conf_mat[:,i])
            
        f1_matrix = 2*(p_matrix*r_matrix)/(p_matrix+r_matrix)
        return p_matrix, r_matrix, f1_matrix

    def compile(self, optimizer, loss, lr=1e-3, metric=None, trainable_params=None):
        """
        Optimizer:  Accepts an optimizer class or a string value that corresponds to a default optimizer class
                        ex.: torch.optim.Adam, "adam", "adagrad" etc.
        Loss:       Accepts an object of a loss class or a string value that corresponds to a default loss class
                        ex.: torch.nn.MSELoss(), "mseloss", "crossentropy"
                        custom loss objects can also be passed as long as they are a subclass of _Loss or Module
        Metric:     Accepts a string either "accuracy", "f1", "confusion"
        Trainable:  Accepts a list of parameters which are to be trained
        Params      defaults to all parameters of the model if not specified
        """
        self.model_compiled=True
        if trainable_params is not None:
            self.trainable_params = trainable_params

        if type(optimizer)==str:
            dict_optim = {
                "adam": torch.optim.Adam,
                "adagrad": torch.optim.Adagrad,
                "sgd": torch.optim.SGD,
            }
            assert optimizer in dict_optim.keys(), "Invalid optimizer string identifier"
            self.optimizer = dict_optim[optimizer](self.trainable_params, lr=lr)
        else:
            self.optimizer = optimizer(trainable_params)
        
        if type(loss)==str:
            dict_loss = {
                "crossentropy": torch.nn.CrossEntropyLoss(),
                "mseloss": torch.nn.MSELoss(),
            }
            assert loss in dict_loss.keys(), "Invalid loss string identifier"
            self.loss_fc=dict_loss[loss]
        else:
            self.loss_fc=loss

        self.metric = metric

    def save_model(self, file_path):
        if not file_path.endswith(".pt"):
            file_path = file_path+".pt"
        torch.save(self, file_path)

    def training_logs(self, eval_metric, epoch):
        self.train_metric.append(eval_metric)
        if self.train_metric[-1]==max(self.train_metric):
            save_path = f"./results/checkpoints/{self.metric}_{self.train_metric[-1]}@epoch_{epoch}.pt"
            self.save_model(save_path)
        with open("./results/training_logs/training_logs.txt", "a") as file:
            file.write(f"{epoch}\t{self.train_metric[-1]}\n")
    
#%%
class VortexDataset(Dataset):
    def __init__(self, data, targets) -> None:
        super().__init__()
        self.data = data
        self.labels = targets

    def __getitem__(self, idx):
        data_point = data[idx]
        torch.tensor(data_point)
        return self.data[idx], self.labels[idx]

    def __len__(self):
        return len(self.data)

data = torch.tensor(new_velocity_data, dtype = torch.float32, device='cuda')
data = torch.einsum('ijklm->imjkl', data)
targets = torch.tensor([id2label[i] for i in flow_type[:, 1]])
dataset = VortexDataset(data, targets)
train_size = int(0.8 * len(dataset))
test_size = len(dataset) - train_size
train_dataset, test_dataset = torch.utils.data.random_split(dataset, [train_size, test_size])
train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=16, shuffle=True)
num_classes = len(np.unique(targets))
#%%

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = ClassifierModel(num_classes, id2label, label2id)
model.compile('adam', "crossentropy", 1e-3, 'accuracy')
model.to(device=device)
#%%
model.fit(train_loader, test_loader, epochs=50)

# %%