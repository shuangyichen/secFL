import numpy as np
import GoWrappers
import os
os.environ['TF_CPP_MIN_LOG_LEVEL']='2'
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from mpi4py import MPI
import argparse
import time

# defining the learning model
class Model:
    def __init__(self, lr):
        inputs = keras.Input(shape=(28, 28, 1), name="digits")
        conv1 = layers.Conv2D(32, (3, 3), activation='relu', padding='same')(inputs)
        pool1 = layers.MaxPool2D()(conv1)
        conv2 = layers.Conv2D(32, (3, 3), activation='relu', padding='same')(pool1)
        pool2 = layers.MaxPool2D()(conv2)
        conv3 = layers.Conv2D(32, (3, 3), activation='relu', padding='same')(pool2)
        pool3 = layers.MaxPool2D()(conv3)
        flatten = layers.Flatten()(pool3)
        x1 = layers.Dense(64, activation="relu")(flatten)
        outputs = layers.Dense(10, name="predictions")(x1)
        # self.model = keras.Model(inputs=tf.cast(inputs, tf.float64), outputs=tf.cast(outputs, tf.float64))
        self.model = keras.Model(inputs=inputs, outputs=outputs)
        self.optimizer = keras.optimizers.SGD(learning_rate=lr)
        self.loss_fn = keras.losses.SparseCategoricalCrossentropy(from_logits=True)
        self.shapes = []
        self.flat_gradient_shape = []
        # print("x",x_train.dtype)
        # print("y",y_train.dtype)
        # self.calculate_gradients(x_train[0:1], y_train[0:1])
        self.calculate_gradients(tf.cast(x_train[0:1], tf.float32), tf.cast(y_train[0:1], tf.float32))
        self.accuracy = []
        self.loss = []

    def calculate_gradients(self, x_train, y_train):
        with tf.GradientTape() as tape:
            # print("x",x_train.dtype)
            logits = self.model(x_train, training=True)
            loss_value = self.loss_fn(y_train, logits)
        grads = tape.gradient(loss_value, self.model.trainable_weights, )
        result = self.flatten_gradients(grads)
        self.flat_gradient_shape = result.numpy().shape
        return self.flatten_gradients(grads)

    def flatten_gradients(self, gradients):
        flat_grad = []
        shapes = []
        for arr in gradients:
            flat_grad.append(tf.reshape(arr, [-1, 1]))
            shapes.append(tf.shape(arr))
        self.shapes = shapes
        return tf.concat(flat_grad, axis=0)

    def unflatten(self, flat_grad):
        output = []
        cntr = 0
        for shape in self.shapes:
            num_elements = tf.math.reduce_prod(shape)
            params = tf.reshape(flat_grad[cntr:cntr + num_elements, 0], shape)
            params = tf.cast(params, tf.float32)
            # params = tf.cast(params, tf.float64)
            cntr += num_elements
            output.append(params)
        return output

    def update_params(self, flat_grad):
        output = self.unflatten(flat_grad)
        self.optimizer.apply_gradients(zip(output, self.model.trainable_weights))
        acc, loss = self.report_performance()
        self.accuracy.append(acc)
        self.loss.append(loss)

    def report_performance(self):
        test_loss = tf.keras.metrics.Mean(name='test_loss')
        test_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(
            name='test_accuracy')
        test_idx = np.random.permutation(len(x_test))
        test_batch_idx = np.array_split(test_idx, 60)
        for batchIdx in test_batch_idx:
            # logits = self.model(x_test[batchIdx], training=False)
            logits = self.model(tf.cast(x_test[batchIdx],tf.float32), training=False)
            lossValue = self.loss_fn(y_test[batchIdx], logits)/len(batchIdx)
            test_accuracy.update_state(y_test[batchIdx], logits)
            test_loss.update_state(lossValue)
        return test_accuracy.result().numpy(), test_loss.result().numpy()

# defining the functionality for the central nodes
def master():
    ### initilize Network setup
    print("Initializing phase 1 at master")
    GoWrappers.server_phase1(server_Address, num_peers, robust, log_degree, log_scale)
    ### letting clients know the server is up
    print("Phase 1 completed")
    for iteration in range(iterations):
        init = time.time()
        ### update model paramaters for clients
        params = model.flatten_gradients(model.model.get_weights())
        param_req = []
        for worker_idx in range(num_peers):
            param_req.append(comm.Isend(np.ascontiguousarray(params, dtype=float), dest=worker_idx + 1, tag=0))
        MPI.Request.waitall(param_req)
        update = GoWrappers.server_phase2(server_Address, num_peers, robust, resiliency, log_degree, log_scale,
                                          input_len)
        model.update_params(np.array(update).reshape(-1, 1)/num_peers)
        res = model.report_performance()
        print("-----------------------------------")
        print("Iteration: ", iteration + 1)
        print("Accuracy: ", round(res[0] * 100, 3))
        print("Loss: ", round(res[1], 5))
        print("Time spent: ", time.time() - init)
        print("-----------------------------------")

# defining the functionality for the client nodes
def client():
    time.sleep(1)
    ### initilize Network setup
    print("Initializing phase 1 at client id ", rank)
    pk, shamir_share, id = GoWrappers.client_phase1(server_Address, robust, log_degree, log_scale, resiliency)
    print("Phase 1 completed at client id ", rank)
    ### upadte model parameters
    for iteration in range(iterations):
        weights = np.zeros(model.flat_gradient_shape, float)
        req = comm.Irecv(weights, source=0, tag=0)
        req.Wait()
        weights = model.unflatten(weights)
        model.model.set_weights(weights)
        part = np.random.permutation(len(x_train))[0:batch_size_per_worker]
        # grad = model.calculate_gradients(x_train[part], y_train[part]).numpy()
        grad = model.calculate_gradients(tf.cast(x_train[part], tf.float32),tf.cast(y_train[part], tf.float32)).numpy()
        tf.cast(x_train[0:1], tf.float32)
        GoWrappers.client_phase2(grad.reshape(-1), pk, shamir_share, id, server_Address, robust, log_degree, log_scale, resiliency)


parser = argparse.ArgumentParser()
parser.add_argument("--num_peers", required=True)
parser.add_argument("--server_address", required=True)
parser.add_argument("--robust", required=True)

parser.add_argument("--learning_rate", required=False, default=0.1)
parser.add_argument("--num_iterations", required=False, default=100)
parser.add_argument("--batch_size_per_worker", required=False, default=256)
parser.add_argument("--resiliency", required=False, default=1)

args = parser.parse_args()
learning_rate = float(args.learning_rate)
if args.robust == "True":
    robust = True
elif args.robust == "False":
    robust = False
else:
    print("Improper robustness value")
iterations = int(args.num_iterations)
batch_size_per_worker = int(args.batch_size_per_worker)
resiliency = float(args.resiliency)
num_peers = int(args.num_peers)

server_Address = args.server_address.encode()
print(iterations)
print(batch_size_per_worker)
print(resiliency)

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
# print(rank)
(x_train, y_train), (x_test, y_test) = keras.datasets.mnist.load_data()
x_train = np.reshape(x_train, (-1, 28, 28, 1)) / 255.
x_test = np.reshape(x_test, (-1, 28, 28, 1)) / 255.
# print(x_train.dtype)
model = Model(learning_rate)
server_Address = b"localhost:8080"
log_degree = 13
log_scale = 40
input_len = model.flat_gradient_shape[0]
if rank == 0:
    print("----------------------------------------")
    print("Master at: ", server_Address)
    print("Number of clients: ", num_peers)
    print("Robustness against dropouts: ", robust, " with resiliency: ", resiliency)
    print("Learining with rate: ", learning_rate, " for ", iterations, " iterations and batch size of ", batch_size_per_worker)
    print("------------------------------------------")
# print(input_len)
if rank == 0:
    master()
else:
    client()

