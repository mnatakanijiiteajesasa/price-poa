// mongo-init/init-replica.js
try {
  var status = db.runCommand({ replSetGetStatus: 1 });
  if (status.ok === 1 && status.myState !== undefined) {
    print('Replica set rs0 already initialised');
  } else {
    rs.initiate({ _id: 'rs0', members: [{ _id: 0, host: 'mongo:27017' }] });
    print('Replica set rs0 initiated');
  }
} catch (e) {
  print('No replset config found, initiating...');
  rs.initiate({ _id: 'rs0', members: [{ _id: 0, host: 'mongo:27017' }] });
  print('Replica set rs0 initiated');
}